"""Cloud provisioning boundaries without billing or account access."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "gcp_remote", Path(__file__).resolve().parents[1] / "cloud_build/gcp_remote.py")
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class GCPRemoteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        state = mock.patch.object(cloud, "STATE", Path(self.temp.name))
        state.start()
        self.addCleanup(state.stop)
        self.args = argparse.Namespace(project="arcium-test-project", zone="us-central1-a",
                                       gcloud="/fake/gcloud", action="create", delete_cache=False)
        self.client = cloud.Cloud(self.args)

    def test_create_bounds_trial_and_uses_separate_private_network(self):
        # Project exists; instance/network/subnet/firewall/cache do not.
        with mock.patch.object(self.client, "describe", side_effect=[{"projectId": self.args.project},
                                                                     None, {"quotas": []}, None, None, None, None]), \
                mock.patch.object(self.client, "run") as run:
            self.client.create()
        calls = [list(c.args) for c in run.call_args_list]
        vm = next(c for c in calls if c[:3] == ["compute", "instances", "create"])
        for flag in ("--machine-type=c4d-highcpu-64", "--provisioning-model=SPOT", "--max-run-duration=2h",
                     "--instance-termination-action=STOP", "--no-service-account", "--no-scopes"):
            self.assertIn(flag, vm)
        self.assertIn("--disk=name=arcium-build-c4d64-cache,device-name=arcium-cache,boot=no,auto-delete=no,mode=rw", vm)
        self.assertIn("--boot-disk-provisioned-iops=3000", vm)
        self.assertIn("--boot-disk-provisioned-throughput=140", vm)
        cache = next(c for c in calls if c[:3] == ["compute", "disks", "create"])
        self.assertIn("--provisioned-iops=3000", cache)
        self.assertIn("--provisioned-throughput=140", cache)
        firewall = next(c for c in calls if c[:3] == ["compute", "firewall-rules", "create"])
        self.assertIn("--source-ranges=35.235.240.0/20", firewall)
        self.assertIn("--allow=tcp:22", firewall)

    def test_insufficient_global_cpu_quota_prevents_billable_disks(self):
        with mock.patch.object(self.client, "describe", side_effect=[{"projectId": self.args.project}, None,
                 {"quotas": [{"metric": "CPUS_ALL_REGIONS", "limit": 12, "usage": 0}]}]), \
                mock.patch.object(self.client, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "quota is below 64"):
                self.client.create()
        self.assertFalse(any(c.args[:1] == ("compute",) for c in run.call_args_list))

    def test_temporary_smoke_worker_fits_twelve_cpu_quota_and_has_its_own_disk(self):
        self.args.smoke_worker = True
        client = cloud.Cloud(self.args)
        with mock.patch.object(client, "describe", side_effect=[{"projectId": self.args.project}, None,
                {"quotas": [{"metric": "CPUS_ALL_REGIONS", "limit": 12, "usage": 0}]}, None, None, None, None]), \
                mock.patch.object(client, "run") as run:
            client.create()
        vm = next(c.args for c in run.call_args_list if c.args[:3] == ("compute", "instances", "create"))
        self.assertEqual(vm[3], "arcium-build-smoke")
        self.assertIn("--machine-type=c4d-highcpu-8", vm)
        self.assertIn("--disk=name=arcium-build-smoke-cache,device-name=arcium-cache,boot=no,auto-delete=no,mode=rw", vm)
        cache = next(c.args for c in run.call_args_list if c.args[:3] == ("compute", "disks", "create"))
        self.assertIn("--size=64GB", cache)
        config = cloud.worker_config(cpus=8)
        self.assertEqual(config["workers"][0]["local"]["platform_properties"]["cpu_count"]["values"], ["8"])
        self.assertEqual(config["stores"][1]["fast_slow"]["fast"]["filesystem"]["eviction_policy"]["max_bytes"], 40_000_000_000)

    def test_retained_undersized_cache_refuses_larger_profile_without_mutation(self):
        self.args.smoke_worker = True
        client = cloud.Cloud(self.args)
        cache = {"labels": {"managed-by": cloud.MANAGER}, "sizeGb": "32"}
        with mock.patch.object(client, "describe", side_effect=[{"projectId": self.args.project}, None,
                {"quotas": []}, {"description": "Arcium cloud build trial; managed by " + cloud.MANAGER},
                {"network": "networks/arcium-build-smoke", "ipCidrRange": "10.77.0.0/24"},
                None, cache]), mock.patch.object(client, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "explicitly expand"):
                client.create()
        self.assertFalse(any(c.args[:3] in (("compute", "disks", "create"),
                                          ("compute", "instances", "create")) for c in run.call_args_list))

    def test_unrelated_vm_prevents_any_compute_mutation(self):
        with mock.patch.object(self.client, "describe", side_effect=[{"projectId": self.args.project},
                                                                     {"labels": {}}]), \
                mock.patch.object(self.client, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "ownership label"):
                self.client.create()
        self.assertFalse(any(c.args[:1] == ("compute",) for c in run.call_args_list))

    def test_existing_managed_vm_is_not_implicitly_restarted(self):
        vm = {"labels": {"managed-by": cloud.MANAGER}, "machineType": "types/" + cloud.MACHINE,
              "status": "TERMINATED"}
        with mock.patch.object(self.client, "describe", side_effect=[{"projectId": self.args.project}, vm]), \
                mock.patch.object(self.client, "run") as run:
            self.client.create()
        self.assertFalse(any(c.args[:1] == ("compute",) for c in run.call_args_list))

    def test_authentication_error_is_not_treated_as_missing_resource(self):
        failure = mock.Mock(returncode=1, stderr="ERROR: You do not currently have an active account selected.")
        with mock.patch.object(self.client, "run", return_value=failure):
            with self.assertRaisesRegex(RuntimeError, "active account"):
                self.client.describe("compute", "instances", "describe", cloud.NAME)

    def test_command_timeout_terminates_sdk_descendants(self):
        marker = Path(self.temp.name) / 'child-terminated'
        child = ("import signal,time,sys; from pathlib import Path; "
                 f"signal.signal(signal.SIGTERM, lambda *a: (Path({str(marker)!r}).write_text('terminated'), sys.exit(0))); "
                 "time.sleep(30)")
        executable = Path(self.temp.name) / 'fake-gcloud'
        executable.write_text(f'#!{sys.executable}\nimport subprocess,sys,time\n'
                              f'subprocess.Popen([sys.executable,"-c",{child!r}])\ntime.sleep(30)\n')
        executable.chmod(0o755)
        self.client.gcloud = str(executable)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.client.run('compute', timeout=1, capture=True)
        self.assertEqual(marker.read_text(), 'terminated')

    def test_dedicated_worker_requires_specific_identity_label(self):
        self.args.worker = 'arcium-build-' + 'c' * 20
        client = cloud.Cloud(self.args)
        with self.assertRaisesRegex(RuntimeError, 'specific worker'):
            client.owned({'labels': {'managed-by': cloud.MANAGER}})

    def test_tunnel_binds_only_localhost_and_uses_iap(self):
        with mock.patch.object(self.client, "run") as run:
            self.client.ssh("--", "-N", "-L", "127.0.0.1:50051:127.0.0.1:50051")
        argv = run.call_args.args
        self.assertIn("--tunnel-through-iap", argv)
        self.assertIn("127.0.0.1:50051:127.0.0.1:50051", argv)

    def test_plan_needs_no_cli_and_initializes_no_resources(self):
        with mock.patch.object(cloud, "Cloud") as client, mock.patch("builtins.print"):
            self.assertEqual(cloud.main(["--project", "arcium-test-project", "plan"]), 0)
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
