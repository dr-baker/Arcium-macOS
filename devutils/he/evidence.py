"""Local structured build evidence, native Siso artifacts, and phase traces.

No exporter or environment capture. Native action times are not wall spans.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import heapq
import json
import os
from pathlib import Path
import queue
import random
import selectors
import shutil
import subprocess
import sys
import threading
import time
import uuid

from .common import HeError, read_json, sha256_file, write_json

_CURRENT = ContextVar('build_evidence', default=None)
_NATIVE = ('siso_metadata.json', 'siso_metrics.json', 'siso_trace.json', 'siso_result.json', 'siso.INFO')
_TIMINGS = ('depsscan_nanos','scandeps_nanos','cache_nanos','queue_nanos', 'input_fetch_nanos', 'exec_nanos', 'worker_nanos', 'output_upload_nanos',
            'materialize_inputs_nanos', 'materialize_outputs_nanos', 'run_nanos')


def current():
    return _CURRENT.get()


def signature(path):
    try:
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    except FileNotFoundError:
        return None


def revision(path):
    if not (path/'.git').exists():
        return None
    try:
        return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'],
                                       text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return None


class Distribution:
    """Bounded deterministic reservoir; exact for <=4096 observations."""
    def __init__(self):
        self.count = 0
        self.total = self.maximum = 0
        self.values = []
        self.random = random.Random(0)

    def add(self, value):
        self.count += 1
        self.total += value
        self.maximum = max(self.maximum, value)
        if len(self.values) < 4096:
            self.values.append(value)
        else:
            index = self.random.randrange(self.count)
            if index < 4096:
                self.values[index] = value

    def report(self):
        values = sorted(self.values)
        return dict(count=self.count, total_action_seconds=self.total / 1e9 if self.count else None,
                    max_seconds=self.maximum / 1e9 if self.count else None,
                    p50_seconds=values[(len(values)-1)//2] / 1e9 if values else None,
                    p95_seconds=values[min(len(values)-1, int(len(values)*.95))] / 1e9 if values else None,
                    quantiles='exact' if self.count <= 4096 else 'reservoir_sample_4096')


def summarize_metrics(path, build_id, *, platform='darwin'):
    """Only a complete JSONL file with matching summaries is attributable."""
    counts = dict(steps=0, local=0, remote=0, cache=0, fallback=0, remote_retry=0, no_exec=0)
    timing = {name: Distribution() for name in _TIMINGS}
    last_summary = None
    final_summary = False
    slow = []
    rss = None
    rss_action = None
    cpu_user = cpu_system = 0
    cpu_count = 0
    try:
        with path.open() as handle:
            for line in handle:
                item = json.loads(line)
                if 'build_id' in item:
                    if item['build_id'] != build_id:
                        return dict(available=False, reason='native build ID mismatch')
                    last_summary = item
                    final_summary = True
                    continue
                final_summary = False
                if 'step_id' not in item:
                    continue
                counts['steps'] += 1
                for name, field in [('local','is_local'), ('remote','is_remote'), ('cache','cached'),
                                    ('fallback','fallback'), ('no_exec','no_exec')]:
                    counts[name] += int(bool(item.get(field)))
                counts['remote_retry'] += int(item.get('remote_retry', 0))
                if item.get('is_local') and all(type(item.get(k)) in (int, float) and
                        0 <= item[k] < float('inf') for k in ('utime_nanos', 'stime_nanos')):
                    cpu_user += item['utime_nanos']
                    cpu_system += item['stime_nanos']
                    cpu_count += 1
                for name in _TIMINGS:
                    value = item.get(name)
                    if isinstance(value, (int, float)) and value >= 0:
                        timing[name].add(value)
                peak = item.get('max_rss')
                if isinstance(peak, (int, float)) and peak > 0 and item.get('is_local'):
                    # Native Darwin Rusage is bytes; Linux Rusage is KiB.
                    peak = peak * (1024 if platform == 'linux' else 1)
                    if rss is None or peak > rss:
                        rss, rss_action = peak, dict(action=item.get('action'), outputs=item.get('outputs'))
                duration = item.get('duration_nanos', 0)
                value = dict(step_id=item['step_id'], action=item.get('action'), outputs=item.get('outputs'),
                             seconds=duration / 1e9, execution_seconds=item.get('exec_nanos', 0) / 1e9,
                             local=bool(item.get('is_local')), remote=bool(item.get('is_remote')))
                heapq.heappush(slow, (duration, item['step_id'], value))
                if len(slow) > 10:
                    heapq.heappop(slow)
    except (OSError, ValueError, TypeError) as error:
        return dict(available=False, reason=f'malformed/incomplete metrics: {type(error).__name__}')
    if not final_summary or last_summary is None or not isinstance(last_summary.get('duration_nanos'), (int,float)):
        return dict(available=False, reason='missing final matching native summary')
    return dict(available=True, build_id=build_id, native_wall_seconds=last_summary['duration_nanos']/1e9,
                counts=counts, action_timings={k.removesuffix('_nanos'): v.report() for k,v in timing.items()},
                max_local_command_rss_bytes=rss, max_rss_action=rss_action,
                local_command_cpu=dict(user_seconds=cpu_user/1e9 if cpu_count else None,
                    system_seconds=cpu_system/1e9 if cpu_count else None,
                    total_seconds=(cpu_user+cpu_system)/1e9 if cpu_count else None,
                    actions_measured=cpu_count, local_actions=counts['local'],
                    note='Native local command rusage only; excludes client preprocessing and cloud CPU. Overlaps sampled process CPU; do not add.'),
                client_input_upload_seconds=None, client_output_download_seconds=None,
                transport_timing_note='Not separately exposed by StepMetric; native trace retained when available.',
                timing_note='Action durations overlap. Totals are action-seconds, not a wall-time breakdown.',
                slowest_actions=[v for _, _, v in sorted(slow, reverse=True)])


class Capture:
    """Always drain compiler pipes; slow sinks use bounded, lossy queues.

    A sink failure or dropped chunk marks evidence incomplete. Queue pressure
    never blocks compiler output; raw files are lossless when sinks keep up.
    """
    def __init__(self, trace, directory, live):
        self.trace, self.directory, self.live = trace, directory, live
        self.readers, self.writers = [], []
        self.done = threading.Event()
        self.paths = {}

    def attach(self, child):
        for name, source, console in [('stdout', child.stdout, sys.stdout), ('stderr', child.stderr, sys.stderr)]:
            path = self.directory / (name + '.txt')
            self.paths[name] = path
            sinks = []
            for target in [path]:
                fifo = queue.Queue(maxsize=128)
                sinks.append(fifo)
                def write(target=target, fifo=fifo, name=name):
                    stream = None
                    failed = False
                    try:
                        if isinstance(target, Path):
                            stream = target.open('wb')
                        while True:
                            chunk = fifo.get()
                            if chunk is None:
                                return
                            if failed:
                                continue
                            try:
                                if stream:
                                    stream.write(chunk)
                                elif hasattr(target, 'buffer'):
                                    target.buffer.write(chunk)
                                    target.buffer.flush()
                                else:
                                    target.write(chunk.decode('utf-8', errors='replace'))
                                    target.flush()
                            except (OSError, ValueError) as error:
                                failed = True
                                self.trace.incomplete(f'{name} sink failed: {type(error).__name__}')
                    except (OSError, ValueError) as error:
                        self.trace.incomplete(f'{name} capture failed: {type(error).__name__}')
                    finally:
                        if stream:
                            try:
                                stream.close()
                            except OSError:
                                self.trace.incomplete(f'{name} capture flush failed')
                writer = threading.Thread(target=write, daemon=True)
                self.writers.append(writer)
                writer.start()
            def read(source=source, sinks=sinks, name=name):
                try:
                    os.set_blocking(source.fileno(), False)
                    with selectors.DefaultSelector() as selector:
                        selector.register(source, selectors.EVENT_READ)
                        while not self.done.is_set():
                            if not selector.select(.2):
                                continue
                            chunk = os.read(source.fileno(),65536)
                            if not chunk:
                                break
                            for fifo in sinks:
                                try:
                                    fifo.put_nowait(chunk)
                                except queue.Full:
                                    self.trace.incomplete(f'{name} sink too slow; output chunks omitted')
                            if self.live:
                                self.trace.deliver(name,chunk)
                except (OSError, ValueError):
                    self.trace.incomplete(f'{name} pipe did not drain completely')
                finally:
                    for fifo in sinks:
                        while True:
                            try:
                                fifo.put_nowait(None)
                                break
                            except queue.Full:
                                try:
                                    fifo.get_nowait()
                                except queue.Empty:
                                    continue
                                self.trace.incomplete(f'{name} sink too slow at EOF; output omitted')
                    source.close()
            reader = threading.Thread(target=read, daemon=True)
            self.readers.append(reader)
            reader.start()

    def finish(self, capture_output=False):
        deadline = time.monotonic() + 5
        for thread in self.readers:
            thread.join(max(0, deadline-time.monotonic()))
        if any(t.is_alive() for t in self.readers):
            self.trace.incomplete('output descriptors remain open after launcher exit')
            self.done.set()
            for thread in self.readers:
                thread.join(.5)
        for thread in self.writers:
            thread.join(max(0, deadline-time.monotonic()))
        if any(t.is_alive() for t in self.writers):
            self.trace.incomplete('output sinks did not finish within five seconds')
        if capture_output:
            return [self.paths[name].read_text(errors='replace') if self.paths[name].exists() else ''
                    for name in ('stdout', 'stderr')]
        return [None, None]


class BuildEvidence:
    def __init__(self, paths, targets, options):
        self.paths = paths
        self.run_id = uuid.uuid4().hex
        self.directory = paths.state / 'build-evidence' / self.run_id
        self.directory.mkdir(parents=True, mode=0o700)
        self.started = time.monotonic_ns()
        self.lock = threading.RLock()
        self.errors = []
        self.reported = set()
        self.console_queues = {}
        self.console_threads = []
        self.stack = []
        self.trace_events = []
        self.events = (self.directory / 'events.jsonl').open('a', buffering=1)
        self.resource_file = (self.directory / 'resources.jsonl').open('a', buffering=1)
        self.peak_rss = None
        self.samples = 0
        self.resource_events = 0
        self.memory_samples = 0
        self.rss_incomplete_samples = 0
        self.record = dict(schema=2, invocation_id=self.run_id, trace_id=self.run_id,
            started_at=datetime.now(timezone.utc).isoformat(), mode='build', outcome='running',
            build_status='not_started', cleanup_status='not_required', evidence_status='complete',
            scope='compile router including plan/admission/worker/cleanup; excludes earlier shell checks and packaging',
            source_worktree=str(paths.worktree), tooling_worktree=str(Path(__file__).resolve().parents[2]),
            build_directory=str(paths.build_dir), output_directory=str(paths.out),
            configuration=getattr(paths, 'build_mode', getattr(paths, 'kind', 'unknown')),
            targets=list(targets), requested_execution=options.get('execution','auto'),
            requested_jobs=options.get('jobs'), requested_remote_jobs=options.get('remote_jobs'), phases=[],
            source_revision=revision(paths.worktree), core_revision=revision(paths.worktree/'helium-chromium'),
            chromium_revision=revision(paths.src),
            tooling_revision=revision(Path(__file__).resolve().parents[2]))
        tools = Path(__file__).resolve().parents[2]
        self.record['tooling_source_sha256'] = {name: sha256_file(tools/name) for name in
            ('dev.sh','build.sh','devutils/he/evidence.py','devutils/he/compile.py','devutils/he/resources.py',
             'devutils/he/remote.py','devutils/he/activity.py','devutils/he/release.py','devutils/he/__main__.py',
             'devutils/cloud_build/gcp_remote.py','devutils/cloud_build/startup.sh') if (tools/name).is_file()}
        args = paths.out / 'args.gn'
        if args.is_file():
            shutil.copyfile(args, self.directory / 'args.gn')
            self.record['args_sha256'] = sha256_file(args)
        for name in ('acquisition.json','applied.json','stamps.json'):
            if (paths.state/name).is_file():
                shutil.copyfile(paths.state/name, self.directory/name)
        self.save()  # Refuse an expensive run if initial evidence cannot persist.
        self.message(f'he build: evidence {self.directory}')

    def incomplete(self, reason):
        with self.lock:
            if reason not in self.errors:
                self.errors.append(reason)

    def warnings(self):
        for error in list(self.errors):
            if error not in self.reported:
                self.reported.add(error)
                self.message(f'warning: build evidence incomplete: {error}')

    def message(self, value):
        self.deliver('stderr',(value+'\n').encode())

    def deliver(self, name, data):
        if name not in self.console_queues:
            fifo = queue.Queue(maxsize=128)
            self.console_queues[name] = fifo
            target = sys.stdout if name=='stdout' else sys.stderr
            def pump():
                failed = False
                while True:
                    chunk = fifo.get()
                    if chunk is None:
                        return
                    if failed:
                        continue
                    try:
                        if hasattr(target,'fileno'):
                            try:
                                fd = target.fileno()
                            except (OSError,ValueError):
                                fd = None
                        else:
                            fd = None
                        if isinstance(fd,int):
                            # No Python stream lock is held during a slow tty
                            # write. All supervisor progress joins this queue.
                            remaining = memoryview(chunk)
                            while remaining:
                                remaining = remaining[os.write(fd,remaining):]
                        else:
                            target.write(chunk.decode(errors='replace'))
                            target.flush()
                    except (OSError,ValueError):
                        failed = True
                        self.incomplete(name+' console unavailable')
            thread = threading.Thread(target=pump,daemon=True)
            self.console_threads.append(thread)
            thread.start()
        fifo = self.console_queues[name]
        for offset in range(0,len(data),65536):
            try:
                fifo.put_nowait(data[offset:offset+65536])
            except queue.Full:
                self.incomplete(name+' console too slow; displayed chunks omitted')

    def close_console(self):
        for fifo in self.console_queues.values():
            while True:
                try:
                    fifo.put_nowait(None)
                    break
                except queue.Full:
                    try:
                        fifo.get_nowait()
                    except queue.Empty:
                        continue
                    self.incomplete('console queue did not drain')
        deadline = time.monotonic()+2
        for thread in self.console_threads:
            thread.join(max(0,deadline-time.monotonic()))
        if any(t.is_alive() for t in self.console_threads):
            self.incomplete('console sink remains blocked; compiler output was independently retained')

    def save(self):
        self.record['evidence_status'] = 'incomplete' if self.errors else 'complete'
        self.record['evidence_errors'] = list(self.errors)
        write_json(self.directory/'manifest.json', self.record)

    def event(self, name, **fields):
        value = dict(schema=1, trace_id=self.run_id, event=name,
                     timestamp=datetime.now(timezone.utc).isoformat(), elapsed_nanos=time.monotonic_ns()-self.started,
                     span_id=self.stack[-1]['span_id'] if self.stack else None, **fields)
        try:
            self.events.write(json.dumps(value, sort_keys=True)+'\n')
        except (OSError, ValueError):
            self.incomplete('cannot persist event stream')
        self.warnings()

    @contextmanager
    def phase(self, name, **attributes):
        start = time.monotonic_ns()
        span = dict(name=name, span_id=uuid.uuid4().hex[:16],
                    parent_span_id=self.stack[-1]['span_id'] if self.stack else None,
                    start_offset_nanos=start-self.started, attributes=attributes, status='running')
        self.stack.append(span)
        self.event('phase_start', phase=name, attributes=attributes)
        try:
            yield span
            if span['status'] == 'running':
                span['status'] = 'ok'
        except BaseException as error:
            span.update(status='error', error_type=type(error).__name__)
            raise
        finally:
            span['duration_seconds'] = (time.monotonic_ns()-start)/1e9
            self.event('phase_end', phase=name, status=span['status'], duration_seconds=span['duration_seconds'])
            self.stack.pop()
            self.record['phases'].append(span)
            self.trace_events.append(dict(name=name, ph='X', ts=(start-self.started)/1000,
                 dur=span['duration_seconds']*1e6, pid=1, tid=1, args=dict(status=span['status'], **attributes)))
            if name == 'worker_cleanup':
                self.record['cleanup_status'] = span['status']

    def child_started(self, command, child, jobs):
        span = self.stack[-1]
        span['attributes'].update(command=command, pid=child.pid, effective_local_jobs=jobs,
                                 admission_seconds=(time.monotonic_ns()-self.started-span['start_offset_nanos'])/1e9,
                                 child_started_offset_nanos=time.monotonic_ns()-self.started)
        if span['name'] == 'build':
            self.record['build_status'] = 'running'
        self.event('child_start', command=command, pid=child.pid, effective_local_jobs=jobs)

    def sample(self, record):
        self.resource_events += 1
        fresh = record.get('resource_sample_fresh',True)
        self.samples += int(fresh)
        rss = record.get('sampled_tree_rss_bytes')
        if rss is not None and fresh:
            self.memory_samples += 1
            self.peak_rss = max(self.peak_rss or 0, rss)
            self.rss_incomplete_samples += int(not record.get('rss_coverage_complete', False))
        try:
            self.resource_file.write(json.dumps(dict(schema=1,trace_id=self.run_id,
                span_id=self.stack[-1]['span_id'] if self.stack else None,
                elapsed_nanos=time.monotonic_ns()-self.started, **record), sort_keys=True)+'\n')
        except (OSError, ValueError):
            self.incomplete('cannot persist resource samples')
        self.warnings()

    def native(self, directory, before):
        artifacts = {}
        for name in _NATIVE:
            source = self.paths.out / name
            if signature(source) is not None and signature(source) != before.get(name):
                try:
                    version = signature(source)
                    shutil.copyfile(source, directory/name)
                    if signature(source) != version or (directory/name).stat().st_size != version[2]:
                        self.incomplete(f'native {name} changed during capture')
                        continue
                    artifacts[name] = dict(bytes=version[2], sha256=sha256_file(directory/name),
                                           attribution='changed_during_owned_phase; no embedded build ID verified')
                except OSError:
                    self.incomplete(f'cannot preserve native {name}')
        metadata = directory/'siso_metadata.json'
        metrics = directory/'siso_metrics.json'
        if 'siso_metadata.json' not in artifacts or 'siso_metrics.json' not in artifacts:
            return dict(available=False, reason='no complete fresh native metadata and metrics pair', artifacts=artifacts)
        try:
            meta = read_json(metadata)
            build_id = meta['build_id']
            platform = meta.get('machine',{}).get('platform',{}).get('os','unknown')
            result = summarize_metrics(metrics, build_id, platform=platform)
            result['artifacts'] = artifacts
            if result['available']:
                for name in ('siso_metadata.json','siso_metrics.json'):
                    artifacts[name]['attribution'] = 'matching_native_build_id'
            result['metadata'] = meta
            return result
        except (OSError, ValueError, KeyError, TypeError) as error:
            return dict(available=False, reason=f'native metadata invalid: {type(error).__name__}')

    def finish(self, status=None, error=None):
        self.record.update(command_wall_seconds=(time.monotonic_ns()-self.started)/1e9,
            finished_at=datetime.now(timezone.utc).isoformat(), returncode=status,
            outcome='exception' if error else 'success' if status == 0 else 'failed',
            error_type=type(error).__name__ if error else None,
            error_message=str(error)[:4096] if error else None,
            observed_tree_rss_peak_bytes=self.peak_rss, resource_samples=self.samples,
            resource_events=self.resource_events, memory_samples=self.memory_samples,
            rss_incomplete_samples=self.rss_incomplete_samples,
            memory_note='Observed sum of RSS during resource-supervised phases, not a true peak. Shared pages may be counted more than once. Excludes preexisting cache daemons, separate SSH/IAP tunnel processes, cloud startup and remote worker RAM.')
        try:
            write_json(self.directory/'phases.trace.json', dict(traceEvents=self.trace_events,displayTimeUnit='ms'))
        except (OSError, ValueError) as problem:
            self.incomplete(f'cannot finalize evidence: {type(problem).__name__}')
        finally:
            for handle in (self.events,self.resource_file):
                try:
                    handle.close()
                except OSError:
                    self.incomplete('cannot flush evidence')
            try:
                self.save()
            except (OSError,ValueError) as problem:
                self.incomplete('cannot finalize manifest: '+type(problem).__name__)
            self.warnings()
            self.close_console()
            try:
                self.save()
            except (OSError,ValueError):
                pass


def recorded_build(function):
    @wraps(function)
    def wrapped(paths, targets, *args, **options):
        try:
            trace = BuildEvidence(paths, targets, options)
        except (OSError, ValueError) as error:
            raise HeError(f'cannot create durable build evidence: {error}') from error
        token = _CURRENT.set(trace)
        status, error = None, None
        try:
            status = function(paths, targets, *args, **options)
            return status
        except BaseException as problem:
            error = problem
            raise
        finally:
            trace.finish(status, error)
            _CURRENT.reset(token)
    return wrapped


def resource_phase(function):
    @wraps(function)
    def wrapped(paths, command, *args, **options):
        trace = current()
        if trace is None:
            return function(paths, command, *args, **options)
        name = options.get('phase','build')
        directory = trace.directory / f'{len(trace.record["phases"]):02d}-{name}'
        directory.mkdir()
        before = {name: signature(paths.out/name) for name in _NATIVE}
        with trace.phase(name, requested_local_jobs=options['jobs']) as span:
            span['attributes']['artifact_directory'] = str(directory)
            try:
                result = function(paths, command, *args, **options)
                span['attributes']['returncode'] = result.returncode
                if result.returncode:
                    span['status'] = 'error'
                if name == 'build':
                    trace.record['build_status'] = 'success' if result.returncode == 0 else 'failed'
                if name == 'plan' and trace.errors:
                    raise HeError('planning evidence is incomplete; cannot safely approve this plan')
                return result
            finally:
                try:
                    with trace.phase('native_archive'):
                        span['attributes']['native'] = trace.native(directory,before)
                except (OSError,ValueError,TypeError,AttributeError) as problem:
                    trace.incomplete('native archive failed: '+type(problem).__name__)
                    span['attributes']['native'] = dict(available=False,reason='archive failed')
    return wrapped


@contextmanager
def phase(name, **attributes):
    trace = current()
    if trace:
        with trace.phase(name, **attributes) as span:
            yield span
    else:
        yield None


def message(value):
    trace = current()
    if trace:
        trace.message(value)
    else:
        print(value,file=sys.stderr,flush=True)


def history(paths, *, limit=20, run_id=None, as_json=False):
    base = paths.state / 'build-evidence'
    if run_id:
        if len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
            raise HeError('use the 32-character build invocation ID')
        record = read_json(base/run_id/'manifest.json')
        if record is None:
            raise HeError('build evidence not found')
        if as_json:
            print(json.dumps(record,indent=2))
            return
        print(f"{run_id}: overall={record.get('outcome')} build={record.get('build_status','unknown')} "
              f"cleanup={record.get('cleanup_status','unknown')} evidence={record.get('evidence_status','legacy')}")
        print(f"Artifacts: {base/run_id}")
        for span in record.get('phases',[]):
            attrs = span.get('attributes',{})
            print(f"  {span['name']}: {span['duration_seconds']:.3f}s ({span['status']})")
            if 'child_wall_seconds' in attrs:
                print(f"    admission={attrs['admission_seconds']:.3f}s child={attrs['child_wall_seconds']:.3f}s")
            native = attrs.get('native',{})
            if native.get('available'):
                print('    Siso '+json.dumps(native['counts'])+f" wall={native['native_wall_seconds']:.3f}s")
                print(f"    max local-command RSS bytes={native['max_local_command_rss_bytes']}")
        print('Action timing distributions and slow actions: use --json. Native traces open in Perfetto.')
        return
    if not 1 <= limit <= 1000:
        raise HeError('history limit must be between 1 and 1000')
    records = []
    for manifest in base.glob('*/manifest.json'):
        try:
            record = read_json(manifest)
            if record.get('mode') != 'build':
                continue
            builds = [p for p in record.get('phases',[]) if p['name']=='build']
            native = builds[-1]['attributes'].get('native',{}) if builds else {}
            records.append(dict(invocation_id=record.get('invocation_id', manifest.parent.name),
                started_at=record.get('started_at'), outcome=record.get('outcome'),
                evidence_status=record.get('evidence_status','legacy'),
                targets=record.get('targets'), wall_seconds=record.get('command_wall_seconds'),
                native=native if native.get('available') else None,
                observed_tree_rss_peak_bytes=record.get('observed_tree_rss_peak_bytes'),
                directory=str(manifest.parent)))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            print(f'warning: unreadable build manifest {manifest}',file=sys.stderr)
    records.sort(key=lambda v:v['started_at'] or '',reverse=True)
    records = records[:limit]
    if as_json:
        print(json.dumps(records,indent=2))
    else:
        print('Start UTC                   Run                               Result   Steps    Pipeline seconds')
        for row in records:
            steps = row['native']['counts']['steps'] if row['native'] else '?'
            seconds = f"{row['wall_seconds']:.3f}" if isinstance(row['wall_seconds'],(int,float)) else '?'
            print(f"{str(row['started_at'])[:26]:26}  {row['invocation_id']}  {str(row['outcome']):7}  {steps!s:7}  {seconds}")
