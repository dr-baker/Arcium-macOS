#!/usr/bin/env python3
"""Freeze Chromium UI dependencies once; rebuild only production Studio sources."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
SDK = LAB / '.build/native-sdk'


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    if path.exists() and path.read_bytes() == data: return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def thin_members(source, out, archives):
    tool = source / 'third_party/llvm-build/Release+Asserts/bin/llvm-ar'
    members = set()
    for name in archives:
        archive = Path(os.path.normpath(out / name))
        if archive.suffix != '.a' or archive.read_bytes()[:8] != b'!<thin>\n': continue
        listing = run([tool, 't', archive.name], cwd=archive.parent, capture_output=True, text=True).stdout
        for member in listing.splitlines():
            members.add(Path(os.path.normpath(archive.parent / member)))
    return members


def file_stamp(path):
    value = path.stat()
    return [value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def frozen_patch_sections(paths):
    import prepare
    result = {}
    for repo in (ROOT / 'helium-chromium', ROOT):
        for raw in (repo / 'patches/series').read_text().splitlines():
            name = raw.split('#')[0].strip()
            if not name: continue
            lines = (repo / 'patches' / name).read_text().splitlines(keepends=True)
            starts = [i for i in range(len(lines) - 1) if lines[i].startswith('--- ') and lines[i + 1].startswith('+++ ')]
            for i, start in enumerate(starts):
                path = prepare.path_name(shlex.split(lines[start + 1][4:].split('\t')[0])[0])
                if path not in paths: continue
                end = starts[i + 1] if i + 1 < len(starts) else len(lines)
                section = ''.join(lines[start:end])
                result.setdefault(path, []).append(hashlib.sha256(section.encode()).hexdigest())
    return result


def validate():
    manifest = json.loads((SDK / 'manifest.json').read_text())
    frozen = manifest.get('frozen_hashes')
    if frozen is None: raise RuntimeError('SDK lacks frozen ABI hashes; recapture it')
    stamps_path = SDK / 'verified-stamps.json'
    stamps = json.loads(stamps_path.read_text()) if stamps_path.exists() else {}
    current = {}
    for relative, expected in frozen.items():
        path = SDK / 'src' / relative
        if not path.is_file(): raise RuntimeError(f'Missing frozen SDK input: {path}')
        stamp = file_stamp(path)
        if stamps.get(relative) != stamp and digest(path) != expected:
            raise RuntimeError(f'Frozen ABI input changed: {path}; recapture matching dependencies')
        current[relative] = stamp
    if frozen_patch_sections(set(frozen)) != manifest['frozen_patch_sections']:
        raise RuntimeError('Owning patches changed a frozen dependency; refresh the SDK')
    write(stamps_path, (json.dumps(current) + '\n').encode())


def export(source):
    source = source.resolve(strict=True)
    if SDK.exists():
        raise RuntimeError(f'SDK already exists; preserve experiments and move it aside before refreshing: {SDK}')
    with tempfile.TemporaryDirectory(prefix='arcium-studio-sdk-', dir='/private/tmp') as temporary:
        report = Path(temporary)
        run([sys.executable, LAB / 'sdk_audit.py', '--source', source, '--report', report])
        info = json.loads((report / 'summary.json').read_text())
        if info['outputs_missing_dependencies'] or info['missing_dependency_files']:
            raise RuntimeError('Completed target dependency records are incomplete')
        commands = json.loads((report / 'target-commands.json').read_text())
        out = source / 'out/Default'
        target = SDK / 'src'
        target_out = target / 'out/Default'
        target_out.mkdir(parents=True)
        copied = set()
        def copy(path):
            path = Path(os.path.normpath(path))
            if not path.is_relative_to(source):
                # System SDK is pinned below, never copy through its symlink.
                raise RuntimeError(f'Unexpected external build input: {path}')
            relative = path.relative_to(source)
            if str(relative) in copied: return
            if not path.is_file(): raise RuntimeError(f'Missing frozen input: {path}')
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination, follow_symlinks=True)
            copied.add(str(relative))
        deps = json.loads((report / 'dependency-files.json').read_text())
        tools = json.loads((report / 'tool-and-include-paths.json').read_text())
        sysroots = [Path(p) for p in tools['external_system_sdk_paths']]
        for dependency in deps:
            path = Path(os.path.normpath(out / dependency))
            resolved = path.resolve(strict=True)
            if any(resolved.is_relative_to(root) for root in sysroots): continue
            copy(path)
        fixed = json.loads((report / 'fixed-prebuilt-inputs.json').read_text())
        for name in fixed: copy(out / name)
        for path in thin_members(source, out, fixed): copy(path)
        for name in json.loads((report / 'dynamic-library-closure.json').read_text())['files']: copy(Path(name))
        for name in tools['tools']: copy(source / name)
        copy(source / 'build/config/warning_suppression.txt')
        for directory in tools['standard_include_directories'] + [tools['clang_runtime_directory']]:
            for path in Path(directory).rglob('*'):
                if path.is_file(): copy(path)
        for entry in commands:
            argv = shlex.split(entry['command'])
            if '-isysroot' in argv:
                name = argv[argv.index('-isysroot') + 1]
                link = target_out / name
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.exists(): link.symlink_to((out / name).resolve(strict=True))
        compiles = [entry for entry in commands if 'linker_driver.py' not in entry['command']]
        source_files = []
        rules = []
        outputs = []
        def escaped(value): return value.replace('$', '$$').replace(' ', '$ ').replace(':', '$:')
        for index, entry in enumerate(compiles):
            argv = shlex.split(entry['command'])
            source_file = argv[argv.index('-c') + 1]
            output = argv[argv.index('-o') + 1]
            depfile = argv[argv.index('-MF') + 1]
            source_files.append(str(Path(os.path.normpath(out / source_file)).relative_to(source)))
            (target_out / output).parent.mkdir(parents=True, exist_ok=True)
            command = entry['command'].removeprefix('sccache ')
            rules += [f'rule compile{index}', '  command = ' + command.replace('$', '$$'),
                      '  depfile = ' + escaped(depfile), '  deps = gcc',
                      f'  description = CXX {source_file}',
                      f'build {escaped(output)}: compile{index} {escaped(source_file)}']
            outputs.append(output)
        link_argv = json.loads((report / 'expanded-link-argv.json').read_text())
        if '=' in link_argv[0]: link_argv.insert(0, 'env')
        rules += ['rule link', '  command = ' + shlex.join(link_argv).replace('$', '$$'),
                  '  description = LINK actual CommandPanelView Studio',
                  'build arcium_command_bar_studio: link ' + ' '.join(map(escaped, outputs)),
                  'default arcium_command_bar_studio']
        write(target_out / 'build.ninja', ('\n'.join(rules) + '\n').encode())
        manifest = {'source': str(source), 'system_sdks': list(map(str, sysroots)),
                    'editable_sources': source_files, 'frozen_files': sorted(copied),
                    'source_hashes': {p: digest(target / p) for p in source_files},
                    'frozen_hashes': {p: digest(target / p) for p in sorted(copied) if p not in source_files},
                    'frozen_patch_sections': frozen_patch_sections(copied - set(source_files)),
                    'audit': info}
        write(SDK / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
        shutil.copytree(report, SDK / 'audit')
        shutil.copy2('/opt/homebrew/bin/ninja', SDK / 'ninja')
        print(f'Independent SDK captured: {len(copied)} files; {len(source_files)} production translation units')


def sync():
    import prepare
    manifest_path = SDK / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    source = SDK / 'src'
    dependencies = set(manifest['frozen_files'])
    # Replay only files originally introduced by our patches. Upstream headers
    # remain frozen with their compiled libraries rather than invented preimages.
    patches = []
    born = set()
    for repo in (ROOT / 'helium-chromium', ROOT):
        for raw in (repo / 'patches/series').read_text().splitlines():
            name = raw.split('#')[0].strip()
            if not name: continue
            path = repo / 'patches' / name
            text = path.read_text()
            lines = text.splitlines()
            for index, line in enumerate(lines[:-1]):
                if line.startswith('+++ ') and lines[index + 1].startswith('@@ -0,0 '):
                    value = prepare.path_name(shlex.split(line[4:].split('\t')[0])[0])
                    if value in dependencies: born.add(value)
            patches.append((path, text))
    previous = prepare.selected
    prepare.selected = lambda path: path in born
    files = {}
    try:
        for path, text in patches:
            prepare.apply_patch(files, text, str(path))
    finally: prepare.selected = previous
    pending = {}
    for path, lines in files.items():
        data = ('\n'.join(lines) + '\n').encode()
        current = source / path
        if current.read_bytes() == data: continue
        if path not in manifest['editable_sources']:
            raise RuntimeError(f'Frozen header/dependency changed: {path}. Refresh the SDK with matching compiled libraries.')
        if digest(current) != manifest['source_hashes'][path]:
            raise RuntimeError(f'Preserve direct SDK experiment before syncing owning patch: {current}')
        pending[path] = data
    for path, data in pending.items():
        write(source / path, data)
        manifest['source_hashes'][path] = digest(source / path)
    write(manifest_path, (json.dumps(manifest, indent=2) + '\n').encode())
    print(f'Synced {len(pending)} production source changes; frozen ABI headers retained')


def build(jobs=6, keep_edits=False):
    if not (SDK / 'manifest.json').exists(): raise RuntimeError('Capture the native SDK first; see README')
    validate()
    if not keep_edits: sync()
    start = time.monotonic()
    run([SDK / 'ninja', '-j', str(jobs)], cwd=SDK / 'src/out/Default')
    elapsed = time.monotonic() - start
    record = {'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'build_seconds': round(elapsed, 3), 'jobs': jobs}
    with (SDK / 'timings.jsonl').open('a') as log: log.write(json.dumps(record) + '\n')
    print(f'Actual renderer build: {elapsed:.2f}s; no GN, Siso, or shared build output')
    return SDK / 'src/out/Default/arcium_command_bar_studio'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'build', 'sync'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--keep-edits', action='store_true', help='Build direct experiments in SDK/src; do not sync patches')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 13: parser.error('--jobs must be 1...13')
    if args.action == 'export':
        if not args.source: parser.error('--source required')
        export(args.source)
    elif args.action == 'sync': sync()
    else: build(args.jobs, args.keep_edits)


if __name__ == '__main__':
    try: main()
    except (RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(error, file=sys.stderr); sys.exit(1)
