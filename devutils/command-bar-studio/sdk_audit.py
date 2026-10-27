#!/usr/bin/env python3
"""Read-only Chromium target audit; writes reports only beneath --report.

Runs Ninja's compdb tool against an extracted manifest, never a build/dry-run.
Reads Siso's Ninja-v4 dependency log directly so Ninja cannot repair/truncate it.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def stamp(path):
    s = path.stat()
    return [s.st_ino, s.st_size, s.st_mtime_ns]


def normalized(path):
    return path[2:] if path.startswith('./') else path


def dependency_records(path, wanted):
    initial = stamp(path)
    paths, selected, latest = [], set(), {}
    records = 0
    with path.open('rb') as stream:
        if stream.read(16) != b'# ninjadeps\n\x04\x00\x00\x00':
            raise ValueError('Expected Ninja dependency log format v4')
        while stream.tell() < initial[1]:
            raw = stream.read(4)
            if len(raw) != 4:
                raise ValueError('Incomplete dependency record size')
            tag, = struct.unpack('<I', raw)
            size = tag & 0x7fffffff
            if size > 524287 or stream.tell() + size > initial[1]:
                raise ValueError('Incomplete or oversized dependency record')
            if tag & 0x80000000:
                if size < 12 or size % 4:
                    raise ValueError('Malformed dependency record')
                output_id, = struct.unpack('<I', stream.read(4))
                if output_id in selected:
                    data = stream.read(size - 4)
                    mtime, = struct.unpack_from('<Q', data)
                    ids = struct.unpack_from('<' + 'I' * ((size - 12) // 4), data, 8)
                    latest[output_id] = (mtime, ids)
                else:
                    stream.seek(size - 4, 1)
            else:
                data = stream.read(size)
                name = data[:-4].rstrip(b'\0').decode()
                checksum, = struct.unpack('<I', data[-4:])
                if (~checksum & 0xffffffff) != len(paths):
                    raise ValueError('Dependency path checksum mismatch')
                if normalized(name) in wanted:
                    selected.add(len(paths))
                paths.append(name)
            records += 1
    if initial != stamp(path):
        raise ValueError('Siso dependency log changed during audit; rerun after build completes')
    return {
        paths[k]: {'mtime_ns': value[0], 'dependencies': [paths[i] for i in value[1]]}
        for k, value in latest.items()
    }, {'records': records, 'path_records': len(paths), 'stamp': initial}


def dylib_closure(out, inputs):
    pending = {(out / value).resolve() for value in inputs if value.endswith('.dylib')}
    visited = set()
    unresolved = set()
    while pending:
        batch = sorted(pending - visited)
        if not batch:
            break
        for value in batch:
            if not value.is_file():
                raise ValueError('Missing dynamic dependency: ' + str(value))
        listing = subprocess.check_output(['otool', '-L', *map(str, batch)], text=True)
        visited.update(batch)
        pending = set()
        current = None
        for line in listing.splitlines():
            if line and not line[0].isspace():
                current = Path(line.rstrip(':'))
                continue
            dependency = line.strip().split(' (', 1)[0]
            if dependency.startswith(('/System/', '/usr/lib/')):
                continue
            if dependency.startswith('@rpath/'):
                destination = out / dependency[len('@rpath/'):]
            elif dependency.startswith('@loader_path/'):
                destination = current.parent / dependency[len('@loader_path/'):]
            elif dependency.startswith('@executable_path/'):
                destination = out / dependency[len('@executable_path/'):]
            elif dependency.startswith('/'):
                destination = Path(dependency)
            elif dependency:
                unresolved.add(dependency)
                continue
            else:
                continue
            pending.add(destination.resolve())
    return {'files': sorted(map(str, visited)), 'unresolved_load_commands': sorted(unresolved)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--ninja', type=Path, default=Path('/opt/homebrew/bin/ninja'))
    args = parser.parse_args()
    src = args.source.resolve(strict=True)
    out = src / 'out/Default'
    report = args.report.resolve()
    if not report.is_relative_to(Path('/private/tmp')):
        parser.error('This audit is restricted to reports beneath /private/tmp')
    report.mkdir(parents=True, exist_ok=True)
    fragment = out / 'obj/chrome/test/arcium_command_bar_studio.ninja'
    toolchain = out / 'toolchain.ninja'
    before = {str(p): stamp(p) for p in (fragment, toolchain)}
    target = fragment.read_text()
    rules = toolchain.read_text().split('\nbuild ', 1)[0]
    pools = set(re.findall(r'^  pool = ([A-Za-z_]+)$', rules, re.M))
    manifest = ''.join('pool ' + p + '\n  depth = 1\n' for p in sorted(pools))
    manifest += rules + '\n'
    # Freeze generated/prebuilt inputs; remove Chromium's huge scheduling-only closure.
    manifest += '\n'.join(
        line.split(' | ', 1)[0].split(' || ', 1)[0] if line.startswith('build ') else line
        for line in target.splitlines()) + '\n'
    mini = report / 'target-only.ninja'
    mini.write_text(manifest)
    result = subprocess.run(
        [str(args.ninja), '-f', str(mini), '-t', 'compdb-targets', '-x', './arcium_command_bar_studio'],
        cwd=out, text=True, capture_output=True, check=True)
    commands = json.loads(result.stdout)
    write_json(report / 'target-commands.json', commands)
    compiles = [entry for entry in commands if 'linker_driver.py' not in entry['command']]
    link = next(entry for entry in commands if 'linker_driver.py' in entry['command'])
    own = set()
    include_paths, sysroots = set(), set()
    for entry in compiles:
        argv = shlex.split(entry['command'])
        own.add(normalized(argv[argv.index('-o') + 1]))
        for index, value in enumerate(argv):
            if value == '-isysroot':
                sysroots.add(str((out / argv[index + 1]).resolve()))
            elif value in ('-I', '-isystem'):
                include_paths.add(str((out / argv[index + 1]).resolve()))
            elif value.startswith('-isystem'):
                include_paths.add(str((out / value[len('-isystem'):]).resolve()))
            elif value.startswith('-I'):
                include_paths.add(str((out / value[2:]).resolve()))
    # Ninja compdb -x retains the quoting around the original @rsp token.
    # Identify that payload by the first own object; parse it as response contents.
    argv = shlex.split(link['command'])
    expanded = []
    for token in argv:
        parts = shlex.split(token) if any(token.startswith(name + ' ') for name in own) else [token]
        expanded.extend(parts)
    write_json(report / 'expanded-link-argv.json', expanded)
    files = [value for value in expanded if value.endswith(('.o', '.a', '.dylib', '.rlib', '.tbd'))]
    fixed = [value for value in files if normalized(value) not in own]
    write_json(report / 'fixed-link-inputs.json', files)
    write_json(report / 'fixed-prebuilt-inputs.json', fixed)
    dynamic_dependencies = dylib_closure(out, fixed)
    write_json(report / 'dynamic-library-closure.json', dynamic_dependencies)
    deps, log_summary = dependency_records(out / '.siso_deps', own)
    write_json(report / 'recorded-dependencies.json', deps)
    union = sorted({value for entry in deps.values() for value in entry['dependencies']})
    write_json(report / 'dependency-files.json', union)
    tools = [
        'third_party/llvm-build/Release+Asserts/bin/clang++',
        'third_party/llvm-build/Release+Asserts/bin/ld64.lld',
        'third_party/llvm-build/Release+Asserts/bin/llvm-strip',
        'third_party/llvm-build/Release+Asserts/bin/llvm-install-name-tool',
        'build/toolchain/apple/linker_driver.py', 'build/toolchain/whole_archive.py',
    ]
    tool_info = {name: {'resolved': str((src / name).resolve(strict=True)),
                        'bytes': (src / name).stat().st_size} for name in tools}
    write_json(report / 'tool-and-include-paths.json', {
        'tools': tool_info, 'ninja': str(args.ninja.resolve()),
        'standard_include_directories': [
            str(src / 'third_party/llvm-build/Release+Asserts/lib/clang/23/include'),
            str(src / 'third_party/libc++/src/include'),
            str(src / 'third_party/libc++abi/src/include'),
        ],
        'clang_runtime_directory': str(src / 'third_party/llvm-build/Release+Asserts/lib/clang/23/lib/darwin'),
        'compiler_include_paths': sorted(include_paths), 'external_system_sdk_paths': sorted(sysroots),
    })
    after = {str(p): stamp(p) for p in (fragment, toolchain)}
    if before != after:
        raise ValueError('GN manifests changed during audit; rerun on the completed target')
    summary = {
        'compile_commands': len(compiles), 'link_commands': 1,
        'fixed_prebuilt_inputs': len(fixed),
        'fixed_prebuilt_bytes': sum((out / value).stat().st_size for value in fixed),
        'runtime_dynamic_libraries': len(dynamic_dependencies['files']),
        'file_types': dict(collections.Counter(Path(value).suffix for value in files)),
        'outputs_with_recorded_dependencies': len(deps),
        'outputs_missing_dependencies': sorted(own - {normalized(value) for value in deps}),
        'dependency_files': len(union),
        'missing_dependency_files': [value for value in union if not (out / value).exists()],
        'dependency_log': log_summary,
        'gn_manifests': {name: {'stamp': value, 'sha256': hashlib.sha256(Path(name).read_bytes()).hexdigest()}
                         for name, value in before.items()},
    }
    write_json(report / 'summary.json', summary)
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in ('gn_manifests', 'dependency_log')}, indent=2))


if __name__ == '__main__':
    main()
