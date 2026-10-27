"""Opt-in remote policy and stable Siso configuration. No cloud calls at setup."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

from .common import HeError, read_json, sha256_file, write_json

SCHEMA = 1


@lru_cache(maxsize=1)
def machine_identity():
    try:
        if sys.platform == 'darwin':
            text = subprocess.check_output(['/usr/sbin/ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                                           text=True, timeout=3)
            value = re.search(r'"IOPlatformUUID"\s*=\s*"([^"\n]+)"', text)[1]
        else:
            value = Path('/etc/machine-id').read_text().strip()
    except (OSError, subprocess.SubprocessError, TypeError):
        raise HeError('cannot identify this machine for a dedicated cloud worker; local builds remain available') from None
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class CompileContext:
    worktree: Path
    build_dir: Path
    out: Path
    kind: str

    @property
    def src(self):
        return self.build_dir / 'src'

    @property
    def state(self):
        return self.build_dir / '.arcium'


def policy(paths, *, disabled=False):
    value = read_json(paths.state / 'remote-build.json')
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('version') != SCHEMA:
        raise HeError('unsupported remote policy; run he agent remote setup again')
    if value.get('build_dir') != str(paths.build_dir.resolve()) or value.get('machine') != machine_identity():
        raise HeError('remote policy belongs to another build directory; run remote setup here to create a separate worker')
    for key, pattern in [('project', r'[a-z][a-z0-9-]{4,28}[a-z0-9]'),
                         ('zone', r'[a-z]+-[a-z]+[0-9]+-[a-z]'),
                         ('worker', r'arcium-build-[a-f0-9]{20}')]:
        if not re.fullmatch(pattern, str(value.get(key, ''))):
            raise HeError(f'invalid remote policy {key}')
    for key, maximum in [('threshold', 10000000), ('remote_jobs', 64)]:
        if type(value.get(key)) is not int or not 1 <= value[key] <= maximum:
            raise HeError(f'invalid remote policy {key}')
    if value.get('cpus',64) not in (8,64):
        raise HeError('remote worker CPUs must be 8 or 64')
    if type(value.get('enabled')) is not bool:
        raise HeError('invalid remote policy enabled flag')
    minimum = value.get('auto_min_compiles')
    if minimum is not None and (type(minimum) is not int or not 1 <= minimum <= 10000000):
        raise HeError('auto_min_compiles must be a positive integer or null')
    if minimum is not None and (type(value.get('auto_basis')) is not str or not value['auto_basis'].strip()):
        raise HeError('automatic routing needs a recorded benchmark basis')
    if type(value.get('retain_boot', False)) is not bool:
        raise HeError('invalid retain_boot flag')
    if not Path(value.get('credentials_dir', '')).is_absolute():
        raise HeError('remote credentials directory must be absolute')
    return value if disabled or value['enabled'] else None


def setup(paths, args):
    existing = read_json(paths.state / 'remote-build.json')
    # A copied build directory gets a fresh identity; a setup in this lane keeps
    # its worker/cache so threshold changes do not leak or invalidate outputs.
    same = (isinstance(existing, dict) and existing.get('build_dir') == str(paths.build_dir.resolve())
            and existing.get('machine') == machine_identity())
    identity = existing.get('worker') if same else None
    if identity is None:
        seed = str(paths.build_dir.resolve()) + str(Path.home().resolve()) + uuid.uuid4().hex
        identity = 'arcium-build-' + hashlib.sha256(seed.encode()).hexdigest()[:20]
    if same and (existing.get('project'), existing.get('zone')) != (args.project, args.zone):
        raise HeError('disable and delete the previous worker before changing project/zone; use a separate build directory')
    cpus = getattr(args,'cpus',64)
    if same and existing.get('cpus',64) != cpus:
        raise HeError('use a separate build directory for a different worker size')
    value = dict(version=SCHEMA, enabled=True, build_dir=str(paths.build_dir.resolve()), machine=machine_identity(),
                 project=args.project, zone=args.zone, worker=identity,
                 threshold=args.threshold, remote_jobs=args.remote_jobs if args.remote_jobs is not None else cpus, cpus=cpus,
                 auto_min_compiles=getattr(args, 'auto_min_compiles', None),
                 auto_basis=getattr(args, 'auto_basis', None), retain_boot=getattr(args, 'retain_boot', False),
                 credentials_dir=str(Path(args.credentials_dir).expanduser().resolve()))
    target = paths.state / 'remote-build.json'
    previous = target.read_bytes() if target.exists() else None
    write_json(target, value)
    try:
        policy(paths)
    except BaseException:
        if previous is None:
            target.unlink()
        else:
            target.write_bytes(previous)
        raise
    mode = ('experimental automatic routing enrolled' if value['auto_min_compiles'] else 'manual remote execution enabled; automatic routing stays local')
    print(f"{mode}. No VM allocated.\n"
          'Run configure --refresh-defaults for each output before remote use.\n'
          f"Worker: {identity}; credentials: {value['credentials_dir']}")


def environment(*, remote=False):
    # CLI flags + generated source config own the endpoint. Ambient settings
    # must never turn a local decision into remote cache/execution traffic.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('SISO_', 'RBE_', 'RECLIENT_'))}
    if 'SISO_LIMITS' in os.environ:
        env['SISO_LIMITS'] = os.environ['SISO_LIMITS']
    if remote:
        env.update(SISO_REAPI_ADDRESS='127.0.0.1:50051', SISO_REAPI_INSTANCE='main',
                   RBE_service_no_security='true')
    return env


def client_limits(environment, jobs=2):
    """Bound client scanning/upload work as well as local compiler work."""
    env = dict(environment)
    limits = {key: jobs for key in ('local', 'preproc', 'scandeps')}
    others = []
    for item in env.get('SISO_LIMITS', '').split(','):
        key, _, value = item.strip().partition('=')
        if key in limits:
            try:
                if int(value) < 1:
                    raise ValueError
                limits[key] = min(limits[key], int(value))
            except ValueError:
                raise HeError(f'SISO_LIMITS {key} must be a positive integer') from None
        elif item.strip():
            others.append(item.strip())
    env['SISO_LIMITS'] = ','.join([*others, *(f'{k}={v}' for k,v in limits.items())])
    return env


def planned_compiles(paths):
    # Pinned Ninja/Siso dry-run descriptions, not total graph edges. Unknown
    # descriptions cannot establish a remote crossover. Stream the full spool.
    count, last, raw, in_build, finished = 0, -1, 0, False, False
    try:
        with (paths.state / 'last-plan.txt').open() as handle:
            for line in handle:
                if line.startswith('build start:'):
                    in_build, finished, raw = True, False, 0
                    continue
                if line.strip() == 'build finished':
                    in_build, finished = False, True
                    continue
                match = re.match(r'^\[\s*(\d+)\s*/\s*\d+\s*\]\s+(?:CC|CXX|OBJC|OBJCXX)\s+\S+\.o(?:\s|$)', line)
                if match and int(match[1]) > last:
                    count += 1
                    last = int(match[1])
                if in_build and raw_compile(line):
                    raw += 1
    except OSError:
        return None
    return raw if finished else count if not in_build else None


def raw_compile(line):
    """Pinned Siso -n prints expanded commands, not progress descriptions."""
    prefix = '../../third_party/llvm-build/Release+Asserts/bin/'
    if not line.startswith((prefix+'clang ', prefix+'clang++ ')):
        return False
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|<>')
        lexer.whitespace_split = True
        words = list(lexer)
        if any(w.startswith('@') or set(w) <= set(';&|<>') for w in words):
            return False
        if any(w in ('-emit-pch','-emit-module','--precompile','-fmodules','-fcxx-modules') or
               w.startswith(('-fmodule-file=','-fmodule-map-file=')) for w in words):
            return False
        source, output = words[words.index('-c')+1], words[words.index('-o')+1]
        return (source.endswith(('.c','.cc','.cpp','.cxx','.m','.mm')) and output.endswith('.o') and
                any(re.fullmatch(r'--target=(arm64|x86_64)-apple-macos(?:[0-9.]*)', w) for w in words))
    except (ValueError, IndexError):
        return False


def configure(paths):
    enabled = policy(paths) is not None
    script = paths.src / 'build/config/siso/configure_siso.py'
    command = [sys.executable, str(script)]
    if enabled:
        command += ['--reapi_address=127.0.0.1:50051', '--reapi_instance=main',
                    '--reapi_backend_config_path=nativelink.star']
    else:
        command += ['--rbe_instance=projects/rbe-chromium-untrusted/instances/default_instance']
    subprocess.run(command, cwd=paths.src, env=environment(), check=True)
    if enabled:
        subprocess.run([sys.executable, str(paths.src / 'tools/clang/scripts/update.py'),
                        '--host-os=linux', '--output-dir=' + str(paths.src / 'third_party/llvm-build/Release+Asserts_linux')],
                       env=environment(), check=True)


def fingerprint(paths):
    files = ['build/config/siso/.sisoenv', 'build/config/siso/backend_config/backend.star',
             'third_party/llvm-build/Release+Asserts_linux/cr_build_revision']
    data = {'schema': SCHEMA, 'args': sha256_file(paths.out / 'args.gn'),
            'source': {p: sha256_file(paths.src / p) if (paths.src / p).is_file() else None for p in files}}
    compiler = paths.src / 'third_party/llvm-build/Release+Asserts_linux/bin/clang'
    if compiler.is_file():
        stat = compiler.stat()
        data['compiler'] = [str(compiler.resolve()), stat.st_size, stat.st_mtime_ns]
    return data


def ready_file(paths):
    return paths.out / '.arcium-remote-ready.json'


def validate_effective(paths):
    gn = paths.out / 'gn'
    result = subprocess.run([str(gn), 'args', str(paths.out), '--list', '--json'], cwd=paths.src,
                            env=environment(), capture_output=True, text=True, check=True)
    values = {item['name']: item.get('current', item.get('default', {})).get('value')
              for item in json.loads(result.stdout)}
    if any(values.get(k) != 'true' for k in ('use_siso', 'use_remoteexec')) or values.get('use_reclient') != 'false':
        raise HeError('remote configuration requires effective use_siso/use_remoteexec=true, use_reclient=false')
    if values.get('cc_wrapper', '""') != '""':
        raise HeError('remote configuration requires an empty cc_wrapper')


def record_ready(paths):
    if policy(paths) is None:
        return
    validate_effective(paths)
    expected = fingerprint(paths)
    if expected['source']['third_party/llvm-build/Release+Asserts_linux/cr_build_revision'] is None or 'compiler' not in expected:
        raise HeError('pinned Linux Clang is missing; configure again')
    write_json(ready_file(paths), expected)


def require_ready(paths):
    try:
        current = fingerprint(paths)
    except OSError as error:
        raise HeError('remote configuration is incomplete; run configure --refresh-defaults') from error
    if read_json(ready_file(paths)) != current:
        raise HeError('remote configuration changed or is missing; run configure --refresh-defaults for this output')
    # GN may have regenerated after an imported .gni changed while args.gn
    # stayed byte-identical. Recheck effective values before any cloud calls.
    validate_effective(paths)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('setup')
    start.add_argument('--project', required=True)
    start.add_argument('--zone', default='us-central1-a')
    start.add_argument('--threshold', type=int, default=500)
    start.add_argument('--remote-jobs', type=int)
    start.add_argument('--cpus', type=int, choices=(8,64), default=8)
    start.add_argument('--auto-min-compiles', type=int,
                       help='experimental opt-in only after a measured end-to-end crossover; otherwise manual only')
    start.add_argument('--auto-basis', help='benchmark run IDs and crossover rationale, including startup/transfer')
    start.add_argument('--retain-boot', action='store_true', help='retain VM/boot for faster startup; costs extra while stopped')
    start.add_argument('--credentials-dir', default='~/.config/arcium/gcloud')
    for action in ('status', 'disable', 'enabled', 'configure', 'record-ready'):
        sub.add_parser(action)
    sub.add_parser('recover')
    worker = sub.add_parser('worker')
    worker.add_argument('worker_action', choices=('plan', 'login', 'create', 'status', 'start', 'stop',
                                                'health', 'logs', 'tunnel', 'delete'))
    worker.add_argument('--delete-cache', action='store_true')
    args = parser.parse_args(argv)
    paths = CompileContext(args.worktree.resolve(), args.build_dir.resolve(),
                           (args.out or args.build_dir / 'src/out/Default').resolve(), 'configuration')
    try:
        if args.action == 'setup':
            setup(paths, args)
        elif args.action == 'status':
            print(json.dumps(policy(paths, disabled=True), indent=2))
        elif args.action == 'disable':
            value = policy(paths, disabled=True)
            if value:
                value['enabled'] = False
                write_json(paths.state / 'remote-build.json', value)
            print('Remote use disabled immediately. Builds run offline. Retained disks are still billable.')
        elif args.action == 'enabled':
            return 0 if policy(paths) else 1
        elif args.action == 'configure':
            configure(paths)
        elif args.action == 'recover':
            from .compile import recover
            recover(paths)
        elif args.action == 'worker':
            from cloud_build import gcp_remote
            config = policy(paths, disabled=True)
            if not config:
                raise HeError('run remote setup before worker operations')
            return gcp_remote.main(['--project', config['project'], '--zone', config['zone'],
                                   '--worker', config['worker'], '--state-dir', str(paths.state / 'cloud'),
                                   '--credentials-dir', config['credentials_dir'], args.worker_action,
                                   *(['--smoke-worker'] if config.get('cpus',64)==8 else []),
                                   *(['--delete-cache'] if args.delete_cache else [])])
        else:
            record_ready(paths)
    except (HeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
