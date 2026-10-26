#!/usr/bin/env python3
"""Provision one private NativeLink worker for an Arcium build trial."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "build/gcp-remote"
NAME = "arcium-build-c4d64"
MANAGER = "arcium-cloud-build"
MACHINE = "c4d-highcpu-64"


def worker_config(root: str = "/var/lib/arcium-worker", port: int = 50051,
                  worker_port: int = 50061, cpus: int = 64) -> dict:
    """Match Chromium's NativeLink cpu_count and large-action properties."""
    def store(name, limit):
        return {"filesystem": {"content_path": f"{root}/{name}/content",
                               "temp_path": f"{root}/{name}/tmp",
                               "eviction_policy": {"max_bytes": limit}}}

    return {
        "stores": [
            {"name": "AC", **store("ac", 1_000_000_000)},
            {"name": "CAS", "fast_slow": {"fast": store("cas", 40_000_000_000 if cpus==8 else 80_000_000_000),
                                           "slow": {"noop": {}}}},
        ],
        "schedulers": [{"name": "MAIN", "simple": {"supported_platform_properties": {
            "cpu_count": "minimum", "label:action_large": "ignore",
            "InputRootAbsolutePath": "ignore"}}}],
        "workers": [{"local": {
            "worker_api_endpoint": {"uri": f"grpc://127.0.0.1:{worker_port}"},
            "cas_fast_slow_store": "CAS",
            "upload_action_result": {"ac_store": "AC"},
            "work_directory": f"{root}/work",
            "platform_properties": {"cpu_count": {"values": [str(cpus)]}},
        }}],
        "servers": [
            {"name": "client", "listener": {"http": {"socket_address": f"127.0.0.1:{port}"}},
             "services": {
                 "cas": [{"instance_name": "main", "cas_store": "CAS"}],
                 "ac": [{"instance_name": "main", "ac_store": "AC"}],
                 "execution": [{"instance_name": "main", "cas_store": "CAS", "scheduler": "MAIN"}],
                 "capabilities": [{"instance_name": "main", "remote_execution": {"scheduler": "MAIN"}}],
                 "bytestream": [{"instance_name": "main", "cas_store": "CAS"}],
             }},
            {"name": "worker", "listener": {"http": {"socket_address": f"127.0.0.1:{worker_port}"}},
             "services": {"worker_api": {"scheduler": "MAIN"}, "health": {}}},
        ],
        "global": {"max_open_files": 24576},
    }


def startup_payload(cpus: int = 64) -> tuple[str, str]:
    template = Path(__file__).with_name("startup.sh").read_text()
    rendered = template.replace("@@NATIVELINK_CONFIG@@", json.dumps(worker_config(cpus=cpus), indent=2))
    rendered = rendered.replace("@@CACHE_MIN_BYTES@@", str((64 if cpus == 8 else 256) * 1024**3))
    fingerprint = hashlib.sha256(rendered.encode()).hexdigest()
    return rendered.replace('@@BOOTSTRAP_SHA256@@', fingerprint), fingerprint


def startup_script(cpus: int = 64) -> str:
    return startup_payload(cpus)[0]


class Cloud:
    def __init__(self, args):
        self.args = args
        self.cpus = 8 if getattr(args, "smoke_worker", False) else 64
        self.machine = f"c4d-highcpu-{self.cpus}"
        self.name = "arcium-build-smoke" if self.cpus == 8 else NAME
        self.name = getattr(args, "worker", None) or self.name
        self.state = Path(getattr(args, "state_dir", None) or STATE).expanduser().resolve()
        self.cache_gb = 64 if self.cpus == 8 else 256
        self.gcloud = args.gcloud or shutil.which("gcloud")
        fallback = Path("/private/tmp/arcium-gcp-builder-tools/google-cloud-sdk/bin/gcloud")
        if not self.gcloud and fallback.is_file():
            self.gcloud = str(fallback)
        if not self.gcloud:
            raise RuntimeError("Install Google Cloud CLI or pass --gcloud PATH")
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        credentials = getattr(args, "credentials_dir", None) or self.state / "gcloud"
        self.env = {**os.environ, "CLOUDSDK_CONFIG": str(Path(credentials).expanduser().resolve()),
                    "CLOUDSDK_CORE_DISABLE_PROMPTS": "1"}

    @contextmanager
    def resource_lock(self):
        with (self.state / (self.name + ".lock")).open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("This worker already has a lifecycle operation/build session") from None
            yield

    def command(self, *argv):
        return [self.gcloud, "--project", self.args.project, *argv]

    def run(self, *argv, capture=False, timeout=180, check=True):
        try:
            from he import evidence
            trace = evidence.current()
        except ImportError:
            trace = None
        if trace is None:
            return self._run(*argv, capture=capture, timeout=timeout, check=check)
        with trace.phase('cloud_cli', operation='.'.join(argv[:3]), timeout_seconds=timeout) as span:
            directory = trace.directory / ('cloud-' + span['span_id'])
            try:
                directory.mkdir()
                span['attributes']['artifact_directory'] = str(directory)
            except OSError:
                trace.incomplete('cannot create cloud CLI output directory; lifecycle operation will still run')
                directory = None
            result, failure = None, None
            try:
                result = self._run(*argv, capture=True, timeout=timeout, check=check)
                return result
            except BaseException as error:
                failure = error
                raise
            finally:
                returncode = getattr(result,'returncode',getattr(failure,'returncode',None))
                span['attributes']['returncode'] = returncode
                if returncode:
                    span['status'] = 'error'
                for name, value in [('stdout', getattr(result, 'stdout', getattr(failure, 'output', None))),
                                    ('stderr', getattr(result, 'stderr', getattr(failure, 'stderr', None)))]:
                    if value is None:
                        continue
                    try:
                        data = value if isinstance(value, bytes) else value.encode()
                        if directory is not None:
                            (directory / (name + '.txt')).write_bytes(data)
                        if not capture:
                            trace.deliver(name,data)
                    except (OSError, ValueError):
                        trace.incomplete('cloud CLI output could not be fully retained or displayed')

    def _run(self, *argv, capture=False, timeout=180, check=True):
        command = self.command(*argv)
        child = subprocess.Popen(command, env=self.env, text=True, start_new_session=True,
                                 stdout=subprocess.PIPE if capture else None,
                                 stderr=subprocess.PIPE if capture else None)
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except BaseException:
            # The SDK can spawn SSH and IAP children. Cancel the whole owned
            # group, including when our session handler raises on SIGTERM.
            previous = {s: signal.signal(s, signal.SIG_IGN) for s in
                        (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
            try:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                    time.sleep(0.2)
                    # Keep the leader unreaped until the final group signal;
                    # its PID cannot be recycled into an unrelated group.
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except PermissionError:
                        # Darwin can reject signals to a zombie-only group.
                        # Accept that only after checking there are no live
                        # members, while our unreaped leader still owns PGID.
                        table = subprocess.run(['/bin/ps', '-axo', 'pgid=,stat='],
                                               capture_output=True, text=True, timeout=2, check=True)
                        for line in table.stdout.splitlines():
                            group, state = line.split()
                            if int(group) == child.pid and not state.startswith('Z'):
                                raise
                except ProcessLookupError:
                    pass
            except (OSError, subprocess.SubprocessError) as error:
                print(f'warning: cannot finish SDK process-group cleanup ({child.pid}): {error}', file=sys.stderr)
            finally:
                try:
                    child.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    print(f'warning: SDK process group {child.pid} has not drained; inspect it before recovery', file=sys.stderr)
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
            raise
        result = subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result

    def describe(self, *argv, timeout=60):
        result = self.run(*argv, "--format=json", capture=True, timeout=timeout, check=False)
        if result.returncode:
            # Authentication, permission and network errors must never be
            # interpreted as an absent resource followed by a create attempt.
            if "was not found" in result.stderr or "notFound" in result.stderr:
                return None
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)

    def owned(self, resource):
        if resource and resource.get("labels", {}).get("managed-by") != MANAGER:
            raise RuntimeError("Refusing an existing resource without this tool's ownership label")
        if resource and getattr(self.args, "worker", None) and resource.get("labels", {}).get("worker-id") != self.name:
            raise RuntimeError("Refusing a resource without this specific worker identity")
        return resource

    def create(self):
        a = self.args
        self.run("auth", "list", "--filter=status:ACTIVE", "--format=value(account)")
        project = self.describe("projects", "describe", a.project)
        if not project:
            raise RuntimeError("Project does not exist; select a billing-enabled project first")
        self.run("services", "enable", "compute.googleapis.com", "iap.googleapis.com", "--quiet")
        name = self.name
        existing = self.owned(self.describe("compute", "instances", "describe", name, "--zone", a.zone))
        if existing:
            if existing["machineType"].rsplit("/", 1)[-1] != self.machine:
                raise RuntimeError("Existing managed instance has a different machine type")
            print(f"Instance already exists: {existing['status']}; use start explicitly if stopped.")
            return
        limits = self.describe("compute", "project-info", "describe")
        for quota in limits.get("quotas", []):
            if quota["metric"] == "CPUS_ALL_REGIONS" and quota["limit"] - quota["usage"] < self.cpus:
                raise RuntimeError(f"CPUs (All Regions) quota is below {self.cpus} available CPUs; request an increase before creating disks")
        # Reject an unavailable machine type/zone before creating billable disks.
        self.run("compute", "machine-types", "describe", self.machine, "--zone", a.zone,
                 "--format=value(name)")
        description = "Arcium cloud build trial; managed by " + MANAGER
        network = self.describe("compute", "networks", "describe", name)
        if network and network.get("description") != description:
            raise RuntimeError("Refusing to reuse an unrelated network")
        if not network:
            self.run("compute", "networks", "create", name, "--subnet-mode=custom",
                     "--description", description, "--quiet")
        region = a.zone.rsplit("-", 1)[0]
        subnet = self.describe("compute", "networks", "subnets", "describe", name, "--region", region)
        if subnet and (not subnet.get("network", "").endswith("/" + name)
                       or subnet.get("ipCidrRange") != "10.77.0.0/24"):
            raise RuntimeError("Existing subnet does not match this worker")
        if not subnet:
            self.run("compute", "networks", "subnets", "create", name, "--network", name,
                     "--region", region, "--range=10.77.0.0/24", "--quiet")
        firewall = self.describe("compute", "firewall-rules", "describe", name + "-iap")
        if firewall and (firewall.get("description") != description
                         or firewall.get("sourceRanges") != ["35.235.240.0/20"]
                         or firewall.get("targetTags") != [name]
                         or firewall.get("direction") != "INGRESS"
                         or firewall.get("allowed") != [{"IPProtocol": "tcp", "ports": ["22"]}]):
            raise RuntimeError("Existing firewall does not match the private IAP SSH rule")
        if not firewall:
            self.run("compute", "firewall-rules", "create", name + "-iap", "--network", name,
                     "--allow=tcp:22", "--source-ranges=35.235.240.0/20", "--target-tags", name,
                     "--description", description, "--quiet")
        cache = self.owned(self.describe("compute", "disks", "describe", name + "-cache", "--zone", a.zone))
        if cache and int(cache["sizeGb"]) < self.cache_gb:
            raise RuntimeError(f"Existing cache disk is smaller than {self.cache_gb} GiB; "
                               "explicitly expand the disk and filesystem before reusing this worker profile")
        if not cache:
            self.run("compute", "disks", "create", name + "-cache", "--zone", a.zone,
                     "--type=hyperdisk-balanced", f"--size={self.cache_gb}GB",
                     "--provisioned-iops=3000", "--provisioned-throughput=140",
                     "--labels=" + self.labels(), "--quiet")
        script = self.state / (name + "-startup.sh")
        script.write_text(startup_script(self.cpus))
        self.run("compute", "instances", "create", name, "--zone", a.zone,
                 "--machine-type=" + self.machine, "--provisioning-model=SPOT",
                 "--instance-termination-action=STOP", "--max-run-duration=2h",
                 "--maintenance-policy=TERMINATE", "--no-restart-on-failure",
                 "--image-family=ubuntu-2404-lts-amd64", "--image-project=ubuntu-os-cloud",
                 "--boot-disk-type=hyperdisk-balanced", "--boot-disk-size=30GB",
                 "--boot-disk-provisioned-iops=3000", "--boot-disk-provisioned-throughput=140",
                 "--network", name, "--subnet", name, "--tags", name,
                 "--no-service-account", "--no-scopes", "--shielded-secure-boot",
                 "--labels=" + self.labels(),
                 "--metadata=enable-oslogin=TRUE,block-project-ssh-keys=TRUE",
                 "--metadata-from-file=startup-script=" + str(script),
                 "--disk=name=" + name + "-cache,device-name=arcium-cache,boot=no,auto-delete=no,mode=rw",
                 "--quiet")

    def labels(self):
        return "managed-by=" + MANAGER + (",worker-id=" + self.name if getattr(self.args, "worker", None) else "")

    def ssh(self, *argv):
        return self.run("compute", "ssh", self.name, "--zone", self.args.zone,
                        "--tunnel-through-iap", "--quiet", "--ssh-key-file", str(self.state / "worker_ssh"),
                        *argv, timeout=None if "-N" in argv else 90)

    def act(self):
        a = self.args
        name = self.name
        if a.action == "login":
            return self.run("auth", "login")
        if a.action == "create":
            return self.create()
        instance = self.owned(self.describe("compute", "instances", "describe", name, "--zone", a.zone))
        if a.action == "status":
            print(json.dumps({"instance": instance, "cache": self.owned(self.describe(
                "compute", "disks", "describe", name + "-cache", "--zone", a.zone))}, indent=2))
            return
        if not instance:
            if a.action == "delete" and a.delete_cache:
                # A failed VM allocation may leave only the explicitly retained
                # cache disk. Still require its ownership label before cleanup.
                cache = self.owned(self.describe("compute", "disks", "describe", name + "-cache", "--zone", a.zone))
                if cache:
                    self.run("compute", "disks", "delete", name + "-cache", "--zone", a.zone, "--quiet")
                return
            raise RuntimeError("No managed worker exists in the selected zone")
        if a.action == "tunnel":
            return self.ssh("--", "-N", "-L", "127.0.0.1:50051:127.0.0.1:50051",
                            "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30")
        if a.action == "logs":
            return self.ssh("--command", "sudo journalctl -u google-startup-scripts -u arcium-nativelink --no-pager -n 100")
        if a.action == "health":
            return self.ssh("--command", "systemctl is-active arcium-nativelink && curl --fail --silent http://127.0.0.1:50061/status")
        if a.action in ("start", "stop", "delete"):
            if instance.get("machineType", "").rsplit("/", 1)[-1] != self.machine:
                raise RuntimeError("Managed instance has an unexpected machine type")
            self.run("compute", "instances", a.action, name, "--zone", a.zone, "--quiet")
            if a.action == "delete" and a.delete_cache:
                self.owned(self.describe("compute", "disks", "describe", name + "-cache", "--zone", a.zone))
                self.run("compute", "disks", "delete", name + "-cache", "--zone", a.zone, "--quiet")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--zone", default="us-central1-a")
    parser.add_argument("--gcloud")
    parser.add_argument("--worker", help="Dedicated worker identity from remote setup")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--credentials-dir", type=Path)
    parser.add_argument("--smoke-worker", action="store_true", help="Use an 8-vCPU worker for a temporary compatibility test")
    parser.add_argument("action", choices=("plan", "login", "create", "status", "start", "stop", "tunnel", "health", "logs", "delete"))
    parser.add_argument("--delete-cache", action="store_true", help="Delete cached build inputs/results with the VM")
    args = parser.parse_args(argv)
    if args.worker and not re.fullmatch(r"arcium-build-[a-f0-9]{20}", args.worker):
        parser.error("invalid dedicated worker identity")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project):
        parser.error("use a Google Cloud project ID, not a project name or number")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+-[a-z]", args.zone):
        parser.error("invalid Google Cloud zone")
    if args.delete_cache and args.action != "delete":
        parser.error("--delete-cache requires delete")
    try:
        if args.action == "plan":
            cpus = 8 if args.smoke_worker else 64
            print(json.dumps({"project": args.project, "zone": args.zone,
                              "instance": args.worker or ("arcium-build-smoke" if args.smoke_worker else NAME),
                              "machine": f"c4d-highcpu-{cpus}", "spot": True, "max_runtime": "2h",
                              "cache_disk_gb": 32 if args.smoke_worker else 256, "boot_disk_gb": 30,
                              "ingress": "SSH via IAP only; NativeLink binds loopback",
                              "stopped_costs": "Both disks remain billable until deleted",
                              "startup": startup_script(cpus)}, indent=2))
        else:
            cloud = Cloud(args)
            with cloud.resource_lock():
                cloud.act()
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
