"""Prepared CI builds use the shared router and keep their Ninja executor."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess

from . import compile, evidence, remote
from .common import HeError, ensure_gclient_markers


@evidence.recorded_build
def compile_prepared(paths, targets, *, arch, jobs=None):
    trace = evidence.current()
    trace.record['executor'] = 'ninja'
    with evidence.phase('ci_preflight'):
        if list(paths.out.glob('siso_*')) or list(paths.out.glob('.siso*')):
            raise HeError('CI archive contains Siso state; refusing to switch it to Ninja')
        result = subprocess.run([str(paths.out / 'gn'), 'args', str(paths.out), '--list', '--json'],
                                cwd=paths.src, env=remote.environment(),
                                capture_output=True, text=True, timeout=30, check=True)
        values = {item['name']: item.get('current', item.get('default', {})).get('value')
                  for item in json.loads(result.stdout)}
        expected = '"arm64"' if arch == 'arm64' else '"x64"'
        if values.get('target_cpu') != expected:
            raise HeError(f'CI archive target_cpu does not match {arch}')
        if any(values.get(key) != 'false' for key in ('use_remoteexec', 'use_reclient')):
            raise HeError('resumable Ninja CI requires effective remote execution and Reclient disabled')
        if values.get('use_siso') != 'false' and not (paths.out / '.ninja_log').is_file():
            raise HeError('CI archive has no established Ninja state or explicit use_siso=false; regenerate it')
        trace.record['ci_configuration'] = {key: values.get(key) for key in
                                            ('target_cpu', 'use_siso', 'use_remoteexec', 'use_reclient')}
        ensure_gclient_markers(paths.build_dir)
    return compile.run.__wrapped__(paths, targets, execution='local', jobs=jobs, failure_limit=1)


def smoke_started(state: Path, since_ns: int, status: int) -> bool:
    """A planning-only timeout or an unfinalized hard kill cannot pass smoke CI."""
    if status not in (0, 124):
        return False
    for path in (state / 'build-evidence').glob('*/manifest.json'):
        try:
            value = json.loads(path.read_text())
            started = datetime.fromisoformat(value['started_at']).timestamp() * 1e9
            if started < since_ns or not value.get('finished_at'):
                continue
            if status == 0 and value.get('returncode') != 0:
                continue
            if value.get('returncode') not in (0, 143):
                continue
            if any(p['name'] == 'build' and 'child_started_offset_nanos' in p.get('attributes', {})
                   for p in value.get('phases', [])):
                return True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False


def main():
    parser = argparse.ArgumentParser(description='Validate that a timed CI smoke reached compilation')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--since-ns', type=int, required=True)
    parser.add_argument('--status', type=int, required=True)
    args = parser.parse_args()
    if not smoke_started(args.state, args.since_ns, args.status):
        parser.exit(1, 'Smoke did not finish or reach a finalized build phase before its deadline.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
