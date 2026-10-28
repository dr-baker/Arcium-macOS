"""One compile router for development and official macOS outputs."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

from . import activity, agent, remote, resources, evidence
from .common import HeError, read_json, write_json


class Interrupted(HeError):
    pass


@contextmanager
def interruptions():
    def stop(signum, frame):
        raise Interrupted(f'build interrupted by signal {signum}')
    previous = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


@contextmanager
def cleaning_up():
    # A repeated group signal must not kill the cleanup subprocess. Cloud CLI
    # operations run in separate sessions and have bounded timeouts.
    previous = {s: signal.signal(s, signal.SIG_IGN) for s in
                (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)}
    try:
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


class CloudSession:
    """A dedicated worker lease; the durable journal survives SIGKILL/reboot."""
    def __init__(self, paths, config):
        from cloud_build.gcp_remote import Cloud
        self.paths = paths
        self.config = config
        self.cloud = Cloud(SimpleNamespace(project=config['project'], zone=config['zone'],
                           worker=config['worker'], state_dir=paths.state / 'cloud',
                           credentials_dir=config['credentials_dir'], gcloud=None,
                           smoke_worker=config.get('cpus',64)==8))
        self.journal = paths.state / 'remote-session.json'
        self.tunnel = None
        self.record = None
        self.lock = None
        self.port = None

    def instance(self, *, timeout=None):
        return self.cloud.owned(self.cloud.describe('compute', 'instances', 'describe', self.cloud.name,
                                                     '--zone', self.config['zone'],
                                                     **({'timeout':timeout} if timeout is not None else {})))

    def cache(self):
        return self.cloud.owned(self.cloud.describe('compute', 'disks', 'describe', self.cloud.name + '-cache',
                                                     '--zone', self.config['zone']))

    def save(self):
        write_json(self.journal, self.record)

    def start(self):
        lock = self.cloud.resource_lock()
        lock.__enter__()
        self.lock = lock
        if self.journal.exists():
            raise HeError('unfinished remote session; run he agent remote recover before using this worker')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        with evidence.phase('worker_inspect'):
            instance, cache = self.instance(), self.cache()
        if instance and instance['status'] not in ('RUNNING', 'TERMINATED'):
            raise HeError('worker is transitioning; inspect remote status before retrying')
        if instance:
            from cloud_build.gcp_remote import startup_script
            metadata = {item['key']: item.get('value') for item in
                        instance.get('metadata', {}).get('items', [])}
            if metadata.get('startup-script') != startup_script(self.config.get('cpus',64)):
                raise HeError('worker bootstrap is outdated; run he agent remote worker delete '
                              '(without --delete-cache), then retry to recreate it with the retained cache')
        self.record = dict(version=1, worker=self.cloud.name, project=self.config['project'],
                           zone=self.config['zone'], started=not instance or instance['status'] != 'RUNNING',
                           created=instance is None, had_cache=cache is not None,
                           retain_boot=self.config.get('retain_boot', False),
                           instance_id=instance.get('id') if instance else None, phase='starting')
        self.save()  # Before the first possibly ambiguous cloud mutation.
        try:
            if not instance:
                with evidence.phase('worker_allocate'):
                    self.cloud.create()
            elif self.record['started']:
                with evidence.phase('worker_start'):
                    self.cloud.run('compute', 'instances', 'start', self.cloud.name, '--zone', self.config['zone'], '--quiet')
        except (subprocess.TimeoutExpired, Interrupted):
            # Killing the CLI does not cancel a server-side operation. Keep
            # recovery mandatory even if an immediate describe finds no VM.
            self.record['ambiguous_operation'] = True
            self.save()
            raise
        instance = self.instance()
        if not instance:
            raise HeError('worker creation did not produce an instance')
        self.record.update(instance_id=instance['id'], phase='connecting')
        self.save()
        if (trace := evidence.current()) is not None:
            trace.record['remote_instance'] = dict(worker=self.cloud.name, instance_id=instance['id'],
                                                   created=self.record['created'], started=self.record['started'])
        with evidence.phase('tunnel_and_worker_ready'):
            self.connect()

    def connect(self):
        from cloud_build.gcp_remote import startup_payload
        expected_bootstrap = startup_payload(self.config.get('cpus',64))[1]
        if (trace := evidence.current()) is not None:
            trace.record['expected_worker_bootstrap_sha256'] = expected_bootstrap
        deadline = time.monotonic() + 300
        attempt = 0
        # RUNNING precedes IAP/SSH visibility on a fresh VM. Use bounded,
        # short-lived probes before owning a persistent tunnel process.
        while time.monotonic() < deadline:
            instance = self.instance(timeout=max(.1,min(20,deadline-time.monotonic())))
            if (not instance or instance['id'] != self.record['instance_id']
                    or instance['status'] != 'RUNNING'):
                raise HeError('worker identity or running state changed during startup')
            attempt += 1
            try:
                health = self.cloud.run('compute', 'ssh', self.cloud.name, '--zone', self.config['zone'],
                    '--tunnel-through-iap', '--quiet', '--ssh-key-file', str(self.cloud.state / 'worker_ssh'),
                    '--command', f'if test "$(cat /etc/arcium-worker/bootstrap-failed 2>/dev/null)" = "{expected_bootstrap}"; '
                                 'then echo ARCIUM_BOOTSTRAP_FAILED >&2; exit 70; fi; '
                                 f'test "$(cat /etc/arcium-worker/bootstrap-id 2>/dev/null)" = "{expected_bootstrap}" && '
                                 'systemctl is-active arcium-nativelink && curl --fail --silent http://127.0.0.1:50061/status',
                    '--', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2',
                    capture=True, check=False, timeout=max(.1,min(20,deadline-time.monotonic())))
                if health.returncode == 0:
                    break
                text = ((getattr(health,'stdout','') or '') + (getattr(health,'stderr','') or '')).lower()
                if 'arcium_bootstrap_failed' in text:
                    try:
                        diagnostic = self.cloud.run('compute', 'ssh', self.cloud.name, '--zone', self.config['zone'],
                            '--tunnel-through-iap', '--quiet', '--ssh-key-file', str(self.cloud.state / 'worker_ssh'),
                            '--command', 'sudo journalctl -u google-startup-scripts -u arcium-nativelink --no-pager -n 100',
                            capture=True, check=False, timeout=20)
                        if (trace := evidence.current()) is not None:
                            (trace.directory/'worker-bootstrap-failure.txt').write_text(
                                (getattr(diagnostic,'stdout','') or '') + (getattr(diagnostic,'stderr','') or ''))
                    except (OSError, subprocess.SubprocessError):
                        if (trace := evidence.current()) is not None:
                            trace.incomplete('cannot capture worker bootstrap failure journal')
                    raise HeError('worker bootstrap failed; inspect worker-bootstrap-failure.txt in build evidence')
                if any(reason in text for reason in ('permission_denied','does not have permission',
                        'host key verification failed','remote host identification has changed','unrecognized arguments')):
                    raise HeError('worker SSH authorization/configuration failed; inspect cloud CLI evidence')
            except (OSError, subprocess.SubprocessError):
                pass
            delay = max(0,min((2,4,8,10)[min(attempt-1,3)],deadline-time.monotonic()))
            if (trace := evidence.current()) is not None:
                trace.event('worker_readiness_retry',attempt=attempt,delay_seconds=delay)
            time.sleep(delay)
        else:
            raise HeError('remote worker did not become healthy within five minutes')
        command = self.cloud.command('compute', 'ssh', self.cloud.name, '--zone', self.config['zone'],
                                    '--tunnel-through-iap', '--quiet', '--ssh-key-file',
                                    str(self.cloud.state / 'worker_ssh'), '--', '-N', '-L',
                                    f'127.0.0.1:{self.port}:127.0.0.1:50051', '-o', 'ExitOnForwardFailure=yes',
                                    '-o', 'ServerAliveInterval=15', '-o', 'ConnectTimeout=15')
        trace = evidence.current()
        log_path = (trace.directory if trace else self.paths.state) / 'remote-tunnel.log'
        if trace:
            trace.record['tunnel_log'] = str(log_path)
        log = log_path.open('w')
        try:
            self.tunnel = subprocess.Popen(command, env=self.cloud.env, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log, start_new_session=True)
        finally:
            log.close()
        while time.monotonic() < deadline:
            if self.tunnel.poll() is not None:
                raise HeError(f'IAP tunnel failed; inspect {log_path}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=1):
                    pass
                self.record['phase'] = 'building'
                self.save()
                return
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(max(0,min(2,deadline-time.monotonic())))
        raise HeError('remote worker did not become healthy within five minutes')

    def close(self, *, failed_start=False):
        with cleaning_up():
            try:
                self._close(failed_start=failed_start)
            finally:
                if self.lock:
                    self.lock.__exit__(None, None, None)
                    self.lock = None

    def _close(self, *, failed_start=False):
        errors = []
        if self.tunnel:
            try:
                os.killpg(self.tunnel.pid, signal.SIGTERM)
                self.tunnel.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.tunnel.pid, signal.SIGKILL)
                    self.tunnel.wait(timeout=5)
                except (OSError, subprocess.SubprocessError) as error:
                    errors.append('tunnel cleanup: ' + str(error))
            except OSError as error:
                errors.append('tunnel cleanup: ' + str(error))
        if self.record:
            try:
                instance = self.instance()
                if instance and self.record['instance_id'] and instance['id'] != self.record['instance_id']:
                    raise HeError('worker instance identity changed; refusing cleanup')
                # Failed creation gets rolled back, including its new cache.
                # Completed sessions stop compute and retain documented disks.
                if instance and self.record['started']:
                    action = 'delete' if self.record['created'] and (failed_start or not self.record.get('retain_boot', True)) else 'stop'
                    self.cloud.run('compute', 'instances', action, self.cloud.name,
                                   '--zone', self.config['zone'], '--quiet')
                if failed_start and self.record['created'] and not self.record['had_cache']:
                    if self.cache():
                        self.cloud.run('compute', 'disks', 'delete', self.cloud.name + '-cache',
                                       '--zone', self.config['zone'], '--quiet')
                if self.record.get('ambiguous_operation'):
                    errors.append('interrupted cloud operation needs explicit reconciliation')
                if not errors:
                    self.journal.unlink(missing_ok=True)
            except (HeError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        if errors:
            raise HeError('remote cleanup incomplete: ' + '; '.join(errors) +
                          '\nSession retained in .arcium/remote-session.json. Run he agent remote recover.')


def recover(paths):
    config = remote.policy(paths, disabled=True)
    if not config:
        raise HeError('no worker policy to recover')
    session = CloudSession(paths, config)
    with session.cloud.resource_lock():
        value = read_json(session.journal)
        if value is None:
            print('No unfinished remote session.')
            return
        if (value.get('worker'), value.get('project'), value.get('zone')) != (config['worker'], config['project'], config['zone']):
            raise HeError('session belongs to a different worker; inspect it manually')
        session.record = value
        if value.get('ambiguous_operation') or value.get('phase') != 'building':
            pending = session.cloud.describe('compute', 'operations', 'list', '--filter',
                      f"targetLink~{config['worker']} AND status!=DONE")
            if pending:
                raise HeError('cloud operations for this worker are still pending; retain the journal and retry recovery after they finish')
            session.record.pop('ambiguous_operation', None)
        session.close(failed_start=value.get('phase') != 'building')


def plan(paths, targets, jobs, *, admit_busy_cpu=False):
    result = resources.run(paths, resources.build_command(paths, targets, planning=True, offline=True),
                           jobs=jobs, capture_output=True, phase='plan', environment=remote.environment(),
                           admit_busy_cpu=admit_busy_cpu)
    with evidence.phase('plan_analysis'):
        edges, output = agent.read_plan(paths,result)
    if result.returncode:
        raise HeError('dry run failed:\n' + output[-2000:])
    return edges, output


def discard_timestamps(paths):
    from . import timestamps
    message = timestamps.discard(paths, 'built while patches were popped')
    if message:
        evidence.message(message)


@evidence.recorded_build
def run(paths, targets, *, jobs=None, execution='auto', remote_jobs=None, guarded=False,
        budget=agent.DEFAULT_EDGE_BUDGET, approved=False, problems=(), session_factory=CloudSession,
        failure_limit=0):
    jobs = resources.jobs_ceiling(jobs)
    requested_jobs = jobs
    config = None if execution == 'local' else remote.policy(paths)
    if config:
        evidence.current().record['remote_policy'] = {
            key: config.get(key) for key in ('project','zone','worker','threshold','remote_jobs',
                                           'auto_min_compiles','auto_basis','retain_boot')}
        evidence.current().record['remote_policy']['cpus'] = config.get('cpus',64)
    if execution == 'remote' and not config:
        raise HeError('remote execution needs remote setup; new developers default to local')
    if remote_jobs is not None and (not config or execution == 'local'):
        raise HeError('--remote-jobs requires an enabled remote policy and auto/remote execution')
    if remote_jobs is not None and not 1 <= remote_jobs <= 64:
        raise HeError('--remote-jobs must be between 1 and 64')
    if guarded:
        if not targets:
            raise HeError('he agent build needs explicit targets')
        from . import timestamps
        if timestamps.pending(paths) or problems:
            raise HeError('build preconditions failed: finish pending timestamps and fix he check problems first')
    edges = None
    initial_activity = activity.sample().record()
    if initial_activity and initial_activity['state'] == 'active':
        jobs = min(jobs, 2)
    if guarded or (config and execution != 'local'):
        planning_overflow = bool(config and (execution == 'remote' or
            (config.get('auto_min_compiles') is not None and initial_activity['state'] == 'active')))
        edges, output = plan(paths, targets, jobs, admit_busy_cpu=planning_overflow)
        if guarded:
            agent.guard_build(paths, targets, budget=budget, approved=approved,
                              problems=list(problems), jobs=jobs, output=output,
                              edge_count=edges, plan_saved=True)
        elif edges is None and execution == 'remote':
            raise HeError('cannot count this dry-run plan; inspect .arcium/last-plan.txt before remote use')
    console = activity.sample().record()
    eligible = remote.planned_compiles(paths) if config else None
    jobs = min(requested_jobs, 2) if console and console['state'] == 'active' else requested_jobs
    minimum = config.get('auto_min_compiles') if config else None
    use_cloud = bool(config and (execution == 'remote' or
        (console['state'] == 'active' and minimum is not None and edges is not None and
         edges > config['threshold'] and eligible is not None and eligible >= minimum)))
    reason = ('explicit remote override' if execution == 'remote' else
              'local policy' if not config else
              'automatic cloud routing has no measured crossover enrollment' if minimum is None else
              f"console {console['state']}; {eligible} recognized compiler actions; minimum {minimum}")
    evidence.current().event('execution_decision', planned_edges=edges, execution='remote' if use_cloud else 'local',
                             threshold=config['threshold'] if config else None, reason=reason,
                             eligible_compiles=eligible, auto_min_compiles=minimum,
                             activity_before_plan=initial_activity, activity_after_plan=console,
                             effective_local_ceiling=jobs)
    evidence.current().record['selected_execution'] = 'remote' if use_cloud else 'local'
    evidence.message(f'he build: {"remote" if use_cloud else "local"} execution ({reason})')
    if not use_cloud:
        discard_timestamps(paths)
        return resources.run(paths, resources.build_command(paths, targets, offline=True, failure_limit=failure_limit), jobs=jobs,
                             environment=remote.client_limits(remote.environment(), jobs) if console and console['state'] == 'active' else remote.environment()).returncode
    session = None
    with interruptions():
        try:
            with evidence.phase('remote_readiness'):
                remote.require_ready(paths)
            if execution == 'auto':
                latest = activity.sample().record()
                evidence.current().event('activity_before_allocation', activity=latest)
                if latest['state'] != 'active':
                    evidence.current().record['selected_execution'] = 'local'
                    evidence.current().event('execution_decision', execution='local',
                        reason='console no longer active before allocation', activity=latest,
                        effective_local_ceiling=requested_jobs)
                    evidence.message('he build: console is no longer active; continuing locally')
                    discard_timestamps(paths)
                    return resources.run(paths, resources.build_command(paths, targets, offline=True, failure_limit=failure_limit),
                        jobs=requested_jobs, environment=remote.environment()).returncode
            jobs = min(requested_jobs, 2)
            session = session_factory(paths, config)
            with evidence.phase('worker_prepare'):
                session.start()
        except (HeError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            if session:
                with evidence.phase('worker_cleanup', failed_start=True):
                    session.close(failed_start=True)  # Cleanup must finish before fallback.
            if isinstance(error, Interrupted) or execution == 'remote':
                if isinstance(error, Interrupted):
                    raise
                raise HeError(str(error)) from error
            evidence.message(f'he build: remote unavailable: {error}\nContinuing offline with {jobs} local jobs.')
            evidence.current().record['selected_execution'] = 'local'
            evidence.current().event('execution_decision', execution='local', reason='remote preparation failed after cleanup')
            discard_timestamps(paths)
            return resources.run(paths, resources.build_command(paths, targets, offline=True, failure_limit=failure_limit), jobs=jobs,
                                 environment=remote.client_limits(remote.environment(), jobs)).returncode
        status = None
        try:
            discard_timestamps(paths)
            command = resources.build_command(paths, targets, remote_jobs=remote_jobs or config['remote_jobs'], offline=False,
                                              failure_limit=failure_limit)
            command[2:2] = ['-strict_remote', '-project=', '-reapi_instance=main', '-reapi_insecure',
                            f'-reapi_address=127.0.0.1:{getattr(session, "port", 50051)}']
            status = resources.run(paths, command, jobs=jobs,
                                   environment=remote.client_limits(remote.environment(remote=True), jobs),
                                   admit_busy_cpu=True).returncode
            return status
        finally:
            try:
                with evidence.phase('worker_cleanup', failed_start=False):
                    session.close()
            except (HeError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                evidence.message(f'he build: {error}')
                if status == 0:
                    raise
