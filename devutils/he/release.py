"""Serialize official builds and route only their compile phase through he."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from .common import HeError
from . import compile, remote
from .lock import _nested, run_locked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', type=Path, required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('held')
    sub.add_parser('lock').add_argument('command', nargs=argparse.REMAINDER)
    sub.add_parser('configure')
    sub.add_parser('record-ready')
    sub.add_parser('enabled')
    sub.add_parser('remote').add_argument('options', nargs=argparse.REMAINDER)
    run = sub.add_parser('compile')
    run.add_argument('--execution', choices=('local', 'auto', 'remote'), default='auto')
    run.add_argument('--jobs', type=int)
    run.add_argument('targets', nargs='+')
    ci = sub.add_parser('ci', help='resume prepared CI output under the release lock')
    ci.add_argument('--arch', choices=('arm64', 'x86_64'), required=True)
    ci.add_argument('--jobs', type=int)
    ci.add_argument('targets', nargs='+')
    args = parser.parse_args(argv)
    root = args.worktree.resolve()
    paths = remote.CompileContext(root, root / 'build', root / 'build/src/out/Default', 'official')
    lock = paths.state / 'release.lock'
    try:
        if args.action == 'held':
            return 0 if _nested(lock) else 1
        if args.action == 'lock':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            return run_locked(lock, command, label='official-build', worktree=root)
        if args.action == 'remote' and not _nested(lock):
            return run_locked(lock, [sys.executable, '-m', 'he.release', '--worktree', str(root),
                                    'remote', *args.options], label='official-remote', worktree=root)
        if args.action == 'ci':
            if (paths.state / 'lane.lock').exists() or (paths.src / '.pc').exists():
                raise HeError('CI resume requires a dedicated release checkout, not a development lane')
            if not _nested(lock):
                return run_locked(lock, [sys.executable, '-m', 'he.release', '--worktree', str(root),
                                        'ci', '--arch', args.arch,
                                        *(['--jobs', str(args.jobs)] if args.jobs else []), *args.targets],
                                  label='ci-build', worktree=root)
        if not _nested(lock):
            raise HeError('official build operation requires its release lock')
        if args.action == 'remote':
            if args.options == ['recover']:
                compile.recover(paths)
                return 0
            return remote.main(['--worktree', str(root), '--build-dir', str(paths.build_dir), *args.options])
        if args.action == 'enabled':
            return 0 if remote.policy(paths) else 1
        if args.action == 'ci':
            from .ci import compile_prepared
            paths = remote.CompileContext(root, paths.build_dir, paths.out, 'ci')
            return compile_prepared(paths, args.targets, arch=args.arch, jobs=args.jobs)
        if args.action == 'configure':
            # The release target can differ from the host running Siso.
            siso = paths.src / 'third_party/siso/cipd/siso'
            if not siso.is_file():
                import platform
                arch = 'mac-arm64' if platform.machine() == 'arm64' else 'mac-amd64'
                import re
                match = re.search(r"'siso_version': '([^']+)'", (paths.src / 'DEPS').read_text())
                if not match:
                    raise HeError('DEPS does not identify the pinned Siso version')
                subprocess.run([str(paths.src / 'third_party/depot_tools/cipd'), 'ensure',
                                '--root', str(siso.parent), '--ensure-file', '-'],
                               input=f'build/siso/{arch} {match[1]}\n', text=True, check=True)
            remote.configure(paths)
        elif args.action == 'record-ready':
            remote.record_ready(paths)
        elif args.action == 'compile':
            return compile.run(paths, args.targets, execution=args.execution, jobs=args.jobs)
    except (HeError, RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
