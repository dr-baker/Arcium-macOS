"""Desktop-friendly build admission and macOS CPU/I/O backoff.

Siso's local concurrency is a startup setting, not a live control. Keep a
bounded ceiling and change OS policy on owned processes without restarting the
graph, suspending jobs, or changing compiler command lines.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import ExitStack
import ctypes
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .common import HeError, Paths, read_json, write_json
from . import evidence

DEFAULT_JOBS = max(1, min(13, (os.cpu_count() or 2) - 1))
INTERVAL = 2.0
RECOVERY_SECONDS = 20.0
TASKPOLICY = Path("/usr/sbin/taskpolicy")


@dataclass(frozen=True)
class Sample:
    cpu_busy: float | None
    memory_free: float | None
    swap_mib_per_second: float | None = None

    @property
    def reason(self) -> str | None:
        if self.memory_free is not None and self.memory_free < 15:
            return "memory headroom below 15%"
        if self.swap_mib_per_second is not None and self.swap_mib_per_second > 16:
            return "swap growth above 16 MiB/s"
        if self.cpu_busy is not None and self.cpu_busy >= 90:
            return "CPU busy at least 90%"
        if self.memory_free is None or self.cpu_busy is None:
            return "resource sensor unavailable"
        return None

    @property
    def recovered(self) -> bool:
        return (self.cpu_busy is not None and self.cpu_busy < 75
                and self.memory_free is not None and self.memory_free >= 25
                and (self.swap_mib_per_second is None or self.swap_mib_per_second < 1))


class Policy:
    """React to memory immediately; debounce CPU and recover slowly."""

    def __init__(self):
        self.background = True  # No optimistic launch before valid readings.
        self.reason = "initial background grace period"
        self.healthy_since = None
        self.busy_since = None

    def update(self, sample: Sample, now: float) -> bool:
        reason = sample.reason
        if reason == "CPU busy at least 90%":
            if self.busy_since is None:
                self.busy_since = now
            if now - self.busy_since < 6:
                reason = None
        else:
            self.busy_since = None
        if reason:
            self.background, self.reason, self.healthy_since = True, reason, None
        elif sample.recovered:
            if self.healthy_since is None:
                self.healthy_since = now
            if now - self.healthy_since >= RECOVERY_SECONDS:
                self.background, self.reason = False, "headroom recovered for 20 seconds"
        else:
            self.healthy_since = None
        return self.background


def _query(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=2, check=False,
                            env={**os.environ, "LC_ALL": "C"})
    if result.returncode:
        raise OSError(f"{Path(argv[0]).name} unavailable")
    return result.stdout


class Sensors:
    def __init__(self):
        self.previous_cpu = None
        self.previous_swap = None

    def _cpu(self) -> float | None:
        if sys.platform != "darwin":
            return None
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        library.mach_host_self.restype = ctypes.c_uint
        library.host_statistics.argtypes = [ctypes.c_uint, ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        ticks = (ctypes.c_uint * 4)()
        count = ctypes.c_uint(4)
        host = library.mach_host_self()
        try:
            if library.host_statistics(host, 3, ticks, ctypes.byref(count)):
                return None
        finally:
            library.mach_port_deallocate(library.mach_task_self(), host)
        current = tuple(ticks)
        previous, self.previous_cpu = self.previous_cpu, current
        if previous is None:
            return None
        delta = [(a - b) & 0xffffffff for a, b in zip(current, previous)]
        return 100 * (1 - delta[2] / sum(delta)) if sum(delta) else 0.0

    def sample(self) -> Sample:
        cpu = memory = swap = None
        try:
            cpu = self._cpu()
        except (OSError, AttributeError):
            pass
        try:
            output = _query(["/usr/bin/memory_pressure", "-Q"])
            match = re.search(r"System-wide memory free percentage:\s*(\d+)%", output)
            memory = float(match[1]) if match else None
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            output = _query(["/usr/bin/vm_stat"])
            size = re.search(r"page size of (\d+) bytes", output)
            pages = re.search(r"Swapouts:\s*(\d+)", output)
            if size and pages:
                current = (time.monotonic(), int(size[1]) * int(pages[1]))
                previous, self.previous_swap = self.previous_swap, current
                if previous and current[0] > previous[0]:
                    swap = max(0, current[1] - previous[1]) / (current[0] - previous[0]) / (1 << 20)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return Sample(cpu, memory, swap)


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    uid: int
    birth: str


class _BSDInfo(ctypes.Structure):
    # macOS SDK sys/proc_info.h, PROC_PIDTBSDINFO (136 bytes). Unlike ps lstart,
    # the start timestamp distinguishes PID replacement within one second.
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "parent", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
    _fields_ += [("nice", ctypes.c_int32), ("seconds", ctypes.c_uint64), ("microseconds", ctypes.c_uint64)]


@lru_cache(maxsize=1)
def _libproc():
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    library.proc_pidinfo.restype = ctypes.c_int
    return library


def _mac_process(pid: int) -> Process | None:
    info = _BSDInfo()
    if _libproc().proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
        return None
    return Process(info.pid, info.parent, info.uid, f"{info.seconds}.{info.microseconds:06d}")


def processes(pid: int | None = None) -> dict[int, Process]:
    """Identity includes birth time; no process-name matching or global signals."""
    if sys.platform == "darwin":
        ids = [pid] if pid is not None else map(int, _query(["/bin/ps", "-axo", "pid="]).split())
        return {p.pid: p for value in ids if (p := _mac_process(value)) is not None}
    result = {}
    command = ["/bin/ps", "-axo", "pid=,ppid=,uid=,lstart="] if pid is None else [
        "/bin/ps", "-p", str(pid), "-o", "pid=,ppid=,uid=,lstart="]
    for line in _query(command).splitlines():
        fields = line.split(None, 3)
        if len(fields) == 4:
            pid, parent, uid = map(int, fields[:3])
            result[pid] = Process(pid, parent, uid, fields[3])
    return result


def same_process(left: Process | None, right: Process) -> bool:
    return left is not None and (left.pid, left.uid, left.birth) == (right.pid, right.uid, right.birth)


class OwnedPolicy:
    def __init__(self, child: subprocess.Popen):
        self.child = child
        self.known: dict[int, Process] = {}
        self.applied: dict[int, bool] = {}
        self.cpu_observed = {}

    def discover(self):
        current = processes()
        # The unreaped direct child cannot have its PID reused. Retain known
        # descendants after reparenting, but discard identities that changed.
        owned = {p.pid for p in self.known.values() if same_process(current.get(p.pid), p)}
        if self.child.poll() is None:
            owned.add(self.child.pid)
        while True:
            added = {p.pid for p in current.values() if p.parent in owned and p.uid == os.getuid()} - owned
            if not added:
                break
            owned |= added
        self.applied = {pid: value for pid, value in self.applied.items()
                        if pid in self.known and same_process(current.get(pid), self.known[pid])}
        self.known = {pid: current[pid] for pid in owned if pid in current}

    def cancel(self, signum: int):
        self.discover()
        # Cancellation stays within the existing command group. In particular,
        # never terminate a detached/shared cache daemon. Send to descendants
        # before the launcher, which may ignore TERM while waiting for Siso.
        for pid in sorted(self.known, key=lambda pid: pid == self.child.pid):
            identity = self.known[pid]
            try:
                if same_process(processes(pid).get(pid), identity) and os.getpgid(pid) == os.getpgrp():
                    os.kill(pid, signum)
            except ProcessLookupError:
                pass

    def update(self, background: bool) -> int:
        if self.child.poll() is not None or not TASKPOLICY.is_file():
            return 0
        self.discover()
        if self.child.pid not in self.known:
            raise OSError("cannot verify build process identity")
        changed = 0
        for pid, identity in self.known.items():
            if self.applied.get(pid) == background:
                continue
            # Revalidate immediately before targeting a PID; never touch an
            # unrelated shared sccache server or a recycled process identity.
            try:
                if not same_process(processes(pid).get(pid), identity):
                    continue
                result = subprocess.run([str(TASKPOLICY), "-b" if background else "-B", "-p", str(pid)],
                                        capture_output=True, timeout=2, check=False)
            except OSError:
                continue  # A short-lived owned process may already be gone.
            if result.returncode == 0:
                self.applied[pid] = background
                changed += 1
            elif same_process(processes(pid).get(pid), identity):
                raise OSError("macOS refused an owned-process policy change")
        self.applied = {pid: value for pid, value in self.applied.items() if pid in self.known}
        return changed


def jobs_ceiling(value: int | None = None) -> int:
    try:
        jobs = value if value is not None else int(os.environ.get("HELIUM_BUILD_JOBS", DEFAULT_JOBS))
        if jobs < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise HeError("HELIUM_BUILD_JOBS / --jobs must be a positive integer") from None
    return jobs


def build_command(paths: Paths, targets: list[str], *, remote_jobs: int | None = None,
                  planning: bool = False, offline: bool = True, failure_limit: int = 0) -> list[str]:
    """Keep the remote worker ceiling independent of desktop admission/backoff."""
    if any(target.startswith("-") for target in targets):
        raise HeError("build targets cannot contain scheduler options; use --jobs / --remote-jobs")
    if type(failure_limit) is not int or failure_limit < 0:
        raise HeError("failure limit must be a nonnegative integer")
    concurrency = ["-j", "{HELIUM_BUILD_JOBS}"]
    args_file = paths.out / "args.gn"
    text = args_file.read_text() if args_file.is_file() else ""
    flags = dict(re.findall(r"^\s*(use_siso|use_remoteexec|use_reclient)\s*=\s*(true|false)\s*(?:#.*)?$",
                            text, re.MULTILINE))
    ci_ninja = getattr(paths, 'kind', None) == 'ci'
    siso = not ci_ninja and flags.get("use_siso") == "true"
    if offline and siso:
        # With remote-ready GN, autoninja turns -j into remote_jobs even when
        # --offline is present. Explicit local_jobs preserves offline builds.
        concurrency = ["-local_jobs={HELIUM_BUILD_JOBS}"]
    if remote_jobs is not None:
        if ci_ninja:
            raise HeError('resumable CI uses local Ninja; remote jobs are unsupported')
        if not isinstance(remote_jobs, int) or remote_jobs < 1:
            raise HeError("--remote-jobs must be a positive integer")
        if flags.get("use_siso") != "true" or flags.get("use_remoteexec") != "true" or flags.get("use_reclient") == "true":
            raise HeError("--remote-jobs requires Siso remote execution without Reclient; configure the endpoint first")
        # autoninja passes these through to Siso. A -j argument would instead
        # become the remote ceiling after local resource admission reduces it.
        concurrency = ["-local_jobs={HELIUM_BUILD_JOBS}", f"-remote_jobs={remote_jobs}"]
    # Resumed CI archives retain Ninja's dependency state. Keep that executor
    # explicit while sharing supervision, logging and lifecycle with Siso.
    launcher = ['ninja'] if ci_ninja else [sys.executable, str(paths.src / "third_party/depot_tools/autoninja.py")]
    return [*launcher,
            *concurrency, *(["--offline"] if offline and not ci_ninja else []),
            *(["-project="] if offline and siso else []),
            "-C", str(paths.out),
            *(["-n"] if planning else ["-k", str(failure_limit)]), *targets]


def siso_limits(jobs: int, limits: str) -> tuple[int, str]:
    """Supply both -j and local=N, including remote-configured offline Siso."""
    others = []
    for item in limits.split(","):
        key, _, value = item.partition("=")
        if key.strip() == "local":
            try:
                if int(value) < 1:
                    raise ValueError
                jobs = min(jobs, int(value))
            except ValueError:
                raise HeError("SISO_LIMITS local must be a positive integer") from None
        elif item.strip():
            others.append(item.strip())
    return jobs, ",".join([*others, f"local={jobs}"])


def cache_environment(paths: Paths, environment: dict) -> str:
    """Keep compiler processes under owned clients; reuse daemon storage.

    Verified with sccache 0.17 and the pinned Siso's inherited local action
    environment. Neither cc_wrapper nor compilation/cache keys change.
    """
    environment["SCCACHE_CLIENT_SIDE"] = "1"
    args = paths.out / "args.gn"
    text = args.read_text() if args.is_file() else ""
    wrapper = re.search(r'^\s*cc_wrapper\s*=\s*"([^"\n]+)"', text, re.MULTILINE)
    words = shlex.split(wrapper[1]) if wrapper else []
    if not words or Path(words[0]).name != "sccache":
        return "client-side requested; no explicit sccache wrapper"
    if "SCCACHE_ERROR_LOG" in environment or environment.get("SCCACHE_DIST_SCHEDULER_URL"):
        raise HeError("resource backoff needs sccache client-side compilation; "
                      "SCCACHE_ERROR_LOG and distributed scheduling disable that mode")
    explicit = environment.get("SCCACHE_CONF")
    if explicit is not None:
        config = Path(explicit)
        if not config.is_absolute():
            raise HeError("resource backoff needs an absolute SCCACHE_CONF path; compiler action directories vary")
    else:
        home = Path(environment.get("HOME", str(Path.home())))
        preferred = home / "Library/Application Support/Mozilla.sccache/config"
        legacy = home / "Library/Preferences/Mozilla.sccache/config"
        config = preferred if preferred.is_file() or not legacy.is_file() else legacy
    if config.is_file():
        import tomllib
        try:
            text = config.read_text()
            data = json.loads(text) if config.suffix == ".json" else tomllib.loads(text)
        except (OSError, ValueError):
            raise HeError("cannot verify sccache configuration for client-side compilation") from None
        if not isinstance(data, dict) or not isinstance(data.get("dist", {}), dict):
            raise HeError("cannot verify sccache configuration for client-side compilation")
        if data.get("dist", {}).get("scheduler_url") is not None:
            raise HeError("resource backoff needs sccache client-side compilation; distributed scheduling disables it")
    executable = shutil.which(words[0], path=environment.get("PATH"))
    if not executable:
        raise HeError("sccache wrapper is configured but its executable is unavailable")
    try:
        output = _query([executable, "--version"])
        version = re.search(r"sccache (\d+)\.(\d+)\.(\d+)", output)
        if not version or tuple(map(int, version.groups())) < (0, 17, 0):
            raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise HeError("resource backoff needs verified sccache client-side support, version 0.17 or later") from None
    return "client-side compilation; shared cache storage"


def status(state: Path) -> dict | None:
    try:
        record = read_json(state / "build-resources.json")
        if isinstance(record, dict):
            updated = record.get("updated")
            record["stale"] = record.get("state") in ("waiting", "running") and (
                not isinstance(updated, (float, int)) or time.time() - updated > 15)
            return record
    except (OSError, ValueError):
        pass
    return None


@lru_cache(maxsize=1)
def _mach_tick_seconds():
    class Timebase(ctypes.Structure):
        _fields_ = [('numer', ctypes.c_uint32), ('denom', ctypes.c_uint32)]
    library = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    library.mach_timebase_info.argtypes = [ctypes.POINTER(Timebase)]
    library.mach_timebase_info.restype = ctypes.c_int
    value = Timebase()
    if library.mach_timebase_info(ctypes.byref(value)) or not value.denom:
        raise OSError('Mach timebase unavailable')
    return value.numer / value.denom / 1e9


def owned_rss(owned: OwnedPolicy) -> dict:
    """Observed sum of live RSS; never a sum/subtraction of per-PID peaks."""
    total, sampled = 0, 0
    for identity in list(owned.known.values()):
        try:
            if not same_process(processes(identity.pid).get(identity.pid), identity):
                continue
            if sys.platform == 'darwin':
                info = ctypes.create_string_buffer(96)  # SDK struct proc_taskinfo
                if _libproc().proc_pidinfo(identity.pid, 4, 0, info, len(info)) != len(info):
                    continue
                resident = ctypes.cast(info, ctypes.POINTER(ctypes.c_uint64))[1]
                counters = ctypes.cast(info, ctypes.POINTER(ctypes.c_uint64))
                cpu = (counters[2] + counters[3]) * _mach_tick_seconds()
            else:
                resident = int(Path(f'/proc/{identity.pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
                cpu = None
            if not same_process(processes(identity.pid).get(identity.pid), identity):
                continue
            total += resident
            sampled += 1
            if cpu is not None:
                key = (identity.pid, identity.uid, identity.birth)
                owned.cpu_observed[key] = max(owned.cpu_observed.get(key, 0), cpu)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            continue
    return dict(sampled_tree_rss_bytes=total if sampled else None,
                observed_process_cpu_seconds=sum(owned.cpu_observed.values()) if owned.cpu_observed else None,
                cpu_process_identities_observed=len(owned.cpu_observed),
                cpu_note='Lower bound: sampled owned process self CPU, Mach ticks converted with timebase; short-lived processes and final unsampled work can be missed. Excludes supervisor, separate SSH/IAP tunnel processes and cloud worker. Never add to native action CPU.',
                rss_processes_sampled=sampled, rss_processes_known=len(owned.known),
                rss_coverage_complete=bool(sampled and sampled == len(owned.known)))


@evidence.resource_phase
def run(paths: Paths, command: list[str], *, jobs: int, sensors=None,
        interval: float = INTERVAL, capture_output: bool = False,
        phase: str = "build", environment: dict | None = None,
        admit_busy_cpu: bool = False) -> subprocess.CompletedProcess:
    """Called inside the existing lane command; never claim/release the lane."""
    sensors = sensors or Sensors()
    environment = dict(os.environ if environment is None else environment)
    environment["SISO_PATH"] = str(paths.src / "third_party/siso/cipd/siso")
    cache_mode = cache_environment(paths, environment)
    policy = Policy()
    record = {"supervisor": os.getpid(), "nonce": os.environ.get("HELIUM_LOCK_NONCE"),
              "requested_jobs": jobs, "state": "waiting", "policy": "background",
              "policy_supported": TASKPOLICY.is_file(), "phase": phase,
              'resource_sample_interval_seconds': interval,
              'admit_busy_cpu': admit_busy_cpu, 'cpu_pressure_admitted': False,
              "cache_mode": cache_mode,
              "progress": {"available": False, "reason": "resource samples are not completed-action telemetry"}}
    record_path = paths.state / "build-resources.json"
    log_path = paths.state / "build-resources.jsonl"
    previous_event = None
    trace = evidence.current()

    def report(sample, *, event=False, **values):
        nonlocal previous_event
        record.update(values, updated=time.time(), sample=asdict(sample), reason=policy.reason,
                      resource_sample_fresh=values.pop('resource_sample_fresh',True))
        try:
            write_json(record_path, record)
        except OSError:
            if trace:
                trace.incomplete('cannot persist latest resource status')
            else:
                raise
        if trace:
            if trace.stack and record.get('resource_sample_fresh', True):
                attrs = trace.stack[-1]['attributes']
                rss = record.get('sampled_tree_rss_bytes')
                if rss is not None:
                    attrs['observed_tree_rss_peak_bytes'] = max(attrs.get('observed_tree_rss_peak_bytes', 0), rss)
                cpu = record.get('observed_process_cpu_seconds')
                if cpu is not None:
                    attrs['observed_process_cpu_seconds'] = cpu
                    attrs['cpu_observation_note'] = record['cpu_note']
            trace.sample(record)
        signature = (record["state"], record["policy"], record["reason"], record.get("policy_error"))
        if event or signature != previous_event:
            try:
                with log_path.open("a") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
            except OSError:
                if trace:
                    trace.incomplete('cannot persist resource transitions')
                else:
                    raise
            error = f"; policy update failed: {record['policy_error']}" if record.get("policy_error") else ""
            jobs_label = record.get("effective_jobs", record["requested_jobs"])
            evidence.message(f"he build: {record['state']}, {record['policy']}, {jobs_label} local jobs: "
                             f"{record['reason']}{error}")
            previous_event = signature

    child = None
    owned = None
    interrupted = None
    completed = False
    output = ExitStack()
    capture = None
    capture_finished = False
    plan_paths = None

    def interrupt(signum, _frame):
        nonlocal interrupted
        interrupted = signum
        # Cancel descendants before their launcher. Killing it here would
        # race the loop's discovery and leave Siso running after reparenting.

    old_handlers = {s: signal.signal(s, interrupt) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
    sample = Sample(None, None)
    try:
        # Only delay launch for known pressure. An unavailable sensor uses
        # one job and background policy, rather than silently removing limits.
        # CPU utilization needs two snapshots. Do not mistake warm-up for a
        # broken sensor and force every build down to one job.
        sensors.sample()
        time.sleep(min(interval, 0.2))
        while not interrupted:
            sample = sensors.sample()
            policy.update(sample, time.monotonic())
            if sample.reason not in (None, "resource sensor unavailable"):
                policy.reason = sample.reason
                if admit_busy_cpu and sample.reason == 'CPU busy at least 90%':
                    policy.background = True
                    policy.reason = 'CPU busy; remote client admitted in background'
                    record['cpu_pressure_admitted'] = True
                    break
                report(sample)
                time.sleep(interval)
                continue
            break
        if interrupted:
            return subprocess.CompletedProcess(command, 128 + interrupted, "", "")
        if sample.recovered:
            policy.background, policy.reason = False, "headroom available at startup"
        record["policy"] = "background" if policy.background else "utility"
        effective, limits = siso_limits(min(jobs, 1) if sample.reason else jobs,
                                        environment.get("SISO_LIMITS", ""))
        record["effective_jobs"] = effective
        record['siso_limits'] = limits
        command = [a.replace("{HELIUM_BUILD_JOBS}", str(effective)) for a in command]
        if TASKPOLICY.is_file():
            command = [str(TASKPOLICY), "-c", "utility", *(["-b"] if policy.background else []), *command]
        if trace and capture_output and phase == 'plan':
            directory = Path(trace.stack[-1]['attributes']['artifact_directory'])
            plan_paths = [directory/(name+'.txt') for name in ('stdout','stderr')]
            stdout, stderr = [output.enter_context(path.open('w+b')) for path in plan_paths]
        elif trace:
            stdout = stderr = subprocess.PIPE
        else:
            stdout = output.enter_context(tempfile.TemporaryFile()) if capture_output else None
            stderr = output.enter_context(tempfile.TemporaryFile()) if capture_output else None
        child = subprocess.Popen(command, cwd=paths.src, env={**environment, "SISO_LIMITS": limits},
                                 stdout=stdout, stderr=stderr)
        owned = OwnedPolicy(child)
        if trace:
            trace.child_started(command, child, effective)
            directory = Path(trace.stack[-1]['attributes']['artifact_directory'])
            if plan_paths is None:
                capture = evidence.Capture(trace, directory, live=not capture_output)
                capture.attach(child)
            else:
                trace.stack[-1]['attributes']['output_capture'] = 'lossless disk spool; bounded in-memory excerpt'
        record["child"] = child.pid
        while True:
            if interrupted:
                owned.cancel(interrupted)
            if child.poll() is not None:
                break
            policy.update(sample, time.monotonic())
            errors = None
            try:
                owned.update(policy.background)
            except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                errors = type(error).__name__
            report(sample, state="running", policy="background" if policy.background else "utility",
                   policy_error=errors, owned_processes=len(owned.known),
                   **(owned_rss(owned) if trace else {}))
            try:
                child.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                sample = sensors.sample()
        result = 128 + interrupted if interrupted else (child.returncode if child.returncode >= 0 else 128 - child.returncode)
        if trace:
            attrs = trace.stack[-1]['attributes']
            attrs['child_wall_seconds'] = (time.monotonic_ns()-trace.started-attrs['child_started_offset_nanos'])/1e9
            trace.event('child_exit', returncode=result, child_wall_seconds=attrs['child_wall_seconds'])
        if capture:
            with evidence.phase('output_drain'):
                captured = capture.finish(capture_output)
            capture_finished = True
        else:
            captured = []
            for handle in (stdout, stderr):
                if handle is not None:
                    handle.seek(0)
                    data = handle.read(1024*1024) if plan_paths else handle.read()
                    if plan_paths and handle.read(1):
                        handle.seek(-min(1024*1024,handle.seek(0,2)),2)
                        data += b'\n[Output excerpt; full plan retained on disk]\n' + handle.read()
                    captured.append(data.decode("utf-8", errors="replace"))
                else:
                    captured.append(None)
        completed = result == 0
        response = subprocess.CompletedProcess(command, result, *captured)
        if plan_paths:
            response.stdout_path, response.stderr_path = plan_paths
        return response
    finally:
        # On monitor failure retain ordinary lane exclusion while the direct
        # child drains. Never certify a failed/interrupted attempt as complete.
        while child is not None:
            if interrupted:
                try:
                    if owned is not None:
                        owned.cancel(interrupted)
                    elif child.poll() is None:
                        child.send_signal(interrupted)
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    # Keep exclusion even if process discovery fails. The
                    # direct unreaped child is still a safe cancellation target.
                    if child.poll() is None:
                        child.send_signal(interrupted)
            if child.poll() is not None:
                break
            try:
                child.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                pass
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        if capture and not capture_finished:
            capture.finish()
        output.close()
        report(sample, event=True, state="finished" if completed and not interrupted else "failed",
               resource_sample_fresh=False,
               returncode=128 + interrupted if interrupted else (child.returncode if child is not None else None),
               launcher_returncode=child.returncode if child is not None else None)
