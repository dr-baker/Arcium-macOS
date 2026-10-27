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
from concurrent.futures import ThreadPoolExecutor

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
                path = prepare.path_name(prepare.header_path(lines[start + 1]))
                if path not in paths: continue
                end = starts[i + 1] if i + 1 < len(starts) else len(lines)
                section = ''.join(lines[start:end])
                result.setdefault(path, []).append(hashlib.sha256(section.encode()).hexdigest())
    return result


def dependency_provenance(editable):
    """Reject changed cached implementations and build definitions as well as ABI."""
    import prepare
    editable = set(editable)
    import iteration
    result = {'browser-configuration': {name: digest(ROOT / name) if (ROOT / name).is_file() else None
                                        for name in iteration.CONFIGURATION_INPUTS}}
    for label, repo, mapping in (('core', ROOT / 'helium-chromium', 'resources/helium_resources.txt'),
                                 ('macos', ROOT, 'resources/platform_resources.txt')):
        sections = []
        for raw in (repo / 'patches/series').read_text().splitlines():
            name = raw.split('#')[0].strip()
            if not name: continue
            lines = (repo / 'patches' / name).read_text().splitlines(keepends=True)
            starts = [i for i in range(len(lines) - 1)
                      if lines[i].startswith('--- ') and lines[i + 1].startswith('+++ ')]
            for i, start in enumerate(starts):
                path = prepare.path_name(prepare.header_path(lines[start + 1]))
                if path == '/dev/null':
                    path = prepare.path_name(prepare.header_path(lines[start]))
                if path in editable or path.startswith(prepare.PREFIX): continue
                end = starts[i + 1] if i + 1 < len(starts) else len(lines)
                sections.append((name, path, hashlib.sha256(''.join(lines[start:end]).encode()).hexdigest()))
        result[label + '/patches'] = sections
        resources = []
        swift_resources = set()
        for raw in (repo / mapping).read_text().splitlines():
            raw = raw.split('#')[0].strip()
            if not raw: continue
            origin, destination = raw.split()
            if destination.startswith(prepare.PREFIX):
                swift_resources.add(origin)
                continue
            path = repo / 'resources' / origin
            resources.append((origin, destination, digest(path) if path.is_file() else 'generated-unavailable'))
        result[label + '/resources'] = resources
        result[label + '/resource-inputs'] = {
            str(path.relative_to(repo / 'resources')): digest(path)
            for path in sorted((repo / 'resources').rglob('*'))
            if path.is_file() and 'generated' not in path.relative_to(repo / 'resources').parts
            and str(path.relative_to(repo / 'resources')) not in swift_resources}
    # JSON arrays are canonical here; don't compare loaded lists with tuples.
    return json.loads(json.dumps(result))


def system_dependencies(commands, out, sysroots, include_linker=True, captured_local=None):
    """Capture actual Apple SDK includes, which normal -MMD records omit."""
    with tempfile.TemporaryDirectory(prefix='studio-system-headers-', dir='/private/tmp') as temporary:
        def probe(item):
            index, entry = item
            argv = shlex.split(entry['command'].removeprefix('sccache '))
            argv = ['-MD' if arg == '-MMD' else arg for arg in argv]
            depfile = Path(temporary) / f'{index}.d'
            argv[argv.index('-MF') + 1] = str(depfile)
            argv[argv.index('-o') + 1] = '/dev/null'
            argv += ['-E', '-Wno-unused-command-line-argument']
            run(argv, cwd=out, capture_output=True)
            text = depfile.read_text().replace('\\\n', '')
            paths = shlex.split(text.split(':', 1)[1])
            resolved = {Path(os.path.normpath(out / name)).resolve(strict=True) for name in paths}
            source_root = out.parents[1].resolve()
            primary_source = Path(os.path.normpath(out / argv[argv.index('-c') + 1])).resolve()
            outside = [path for path in resolved if path != primary_source and not path.is_relative_to(source_root)
                       and not any(path.is_relative_to(root) for root in sysroots)]
            if outside: raise RuntimeError('Uncaptured external compiler input: ' + str(sorted(outside)[0]))
            if captured_local is not None:
                uncaptured = {str(path.relative_to(source_root)) for path in resolved
                              if path != primary_source and path.is_relative_to(source_root)} - set(captured_local)
                if uncaptured:
                    raise RuntimeError('Uncaptured local compiler input requires a matching capture: ' + sorted(uncaptured)[0])
            return {str(path) for path in resolved if any(path.is_relative_to(root) for root in sysroots)}
        with ThreadPoolExecutor(max_workers=4) as executor:
            paths = set().union(*executor.map(probe, enumerate(commands)))
    for root in sysroots:
        paths.update(str(path.resolve()) for path in root.glob('SDKSettings.*') if path.is_file())
        if include_linker:
            # Freeze the SDK stub closure conservatively, including reexports.
            paths.update(str(path.resolve()) for path in root.rglob('*.tbd') if path.is_file())
    return {path: digest(Path(path)) for path in sorted(paths)}


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
    if 'dependency_provenance' not in manifest:
        raise RuntimeError('SDK lacks cached-implementation provenance; refresh the SDK')
    if dependency_provenance(manifest['editable_sources']) != manifest['dependency_provenance']:
        raise RuntimeError('Cached implementation, resource, or build definition changed; refresh the SDK')
    for relative, expected in manifest.get('sysroot_mappings', {}).items():
        link = SDK / relative
        if not link.exists() or str(link.resolve()) != expected:
            raise RuntimeError(f'External sysroot mapping changed: {relative}; refresh the SDK')
    for absolute, expected in manifest['system_dependency_hashes'].items():
        path = Path(absolute)
        if not path.is_file(): raise RuntimeError(f'External SDK input is missing: {path}')
        stamp = file_stamp(path)
        key = 'external/' + absolute
        if stamps.get(key) != stamp and digest(path) != expected:
            raise RuntimeError(f'External SDK input changed: {path}; refresh the SDK')
        current[key] = stamp
    for relative, expected in manifest['graph_hashes'].items():
        if digest(SDK / relative) != expected:
            raise RuntimeError(f'Cached build graph/tool changed: {relative}; refresh the SDK')
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
        shutil.copy2('/opt/homebrew/bin/ninja', SDK / 'ninja')
        write(target_out / 'args.gn', (out / 'args.gn').read_bytes())
        sysroot_mappings = {}
        for entry in compiles:
            argv = shlex.split(entry['command'])
            if '-isysroot' in argv:
                link = target_out / argv[argv.index('-isysroot') + 1]
                key = str(link.relative_to(SDK)) if link.is_relative_to(SDK) else str(link)
                sysroot_mappings[key] = str(link.resolve(strict=True))
        manifest = {'source': str(source), 'system_sdks': list(map(str, sysroots)),
                    'editable_sources': source_files, 'frozen_files': sorted(copied),
                    'source_hashes': {p: digest(target / p) for p in source_files},
                    'frozen_hashes': {p: digest(target / p) for p in sorted(copied) if p not in source_files},
                    'frozen_patch_sections': frozen_patch_sections(copied - set(source_files)),
                    'dependency_provenance': dependency_provenance(source_files),
                    'system_dependency_hashes': system_dependencies(compiles, out, sysroots),
                    'sysroot_mappings': sysroot_mappings,
                    'graph_hashes': {p: digest(SDK / p) for p in
                                     ('src/out/Default/build.ninja', 'src/out/Default/args.gn', 'ninja')},
                    'compile_commands': compiles, 'link_arguments': link_argv,
                    'audit': info}
        write(SDK / 'manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
        shutil.copytree(report, SDK / 'audit')
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
                    value = prepare.path_name(prepare.header_path(line))
                    if value in dependencies: born.add(value)
            patches.append((path, text))
    previous = prepare.selected
    prepare.selected = lambda path: path in born
    files = {}
    try:
        for path, text in patches:
            prepare.apply_patch(files, text, str(path))
    finally: prepare.selected = previous
    host = 'chrome/test/arcium_command_bar_studio_mac.mm'
    if host in manifest['editable_sources']:
        source_host = ROOT / 'devutils/command-bar-studio/native_host.mm'
        if not source_host.exists(): source_host = LAB / 'native_host.mm'
        files[host] = source_host.read_text().splitlines()
    pending = {}
    for path, lines in files.items():
        data = ('\n'.join(lines) + '\n').encode()
        current = source / path
        if current.read_bytes() == data:
            # Porting an experiment adopts these exact bytes as the new baseline.
            # A later production edit must not be mistaken for an unported edit.
            if path in manifest['editable_sources']:
                manifest['source_hashes'][path] = digest(current)
            continue
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


def experiment_inputs():
    manifest = json.loads((SDK / 'manifest.json').read_text())
    return {'.sdk-experiments/' + name: SDK / 'src' / name for name in manifest['editable_sources']}


def frozen_source_graph(manifest, experiments=None):
    """Compiler inputs stay immutable even if an editor changes SDK experiments."""
    out = SDK / 'src/out/Default'
    objects = SDK / 'source-generations'
    objects.mkdir(exist_ok=True)
    sources = {}
    for relative in manifest['editable_sources']:
        source = experiments[relative][0] if experiments else SDK / 'src' / relative
        data = source.read_bytes()
        identity = hashlib.sha256(data).hexdigest()
        if experiments and identity != experiments[relative][1]:
            raise RuntimeError('Immutable SDK experiment was modified; previous app retained')
        destination = objects / identity / Path(relative).name
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            if digest(destination) != identity: raise RuntimeError('Immutable compiler source was modified')
        else:
            destination.write_bytes(data)
            destination.chmod(0o444)
        sources[relative] = (identity, destination)
    rules = []
    outputs = []
    def escaped(value): return str(value).replace('$', '$$').replace(' ', '$ ').replace(':', '$:')
    for index, entry in enumerate(manifest['compile_commands']):
        argv = shlex.split(entry['command'].removeprefix('sccache '))
        original = argv[argv.index('-c') + 1]
        relative = str(Path(os.path.normpath(out / original)).relative_to(SDK / 'src'))
        _, frozen = sources[relative]
        argv[argv.index('-c') + 1] = str(frozen)
        argv += ['-iquote', str((SDK / 'src' / relative).parent),
                 f'-ffile-prefix-map={frozen}={original}']
        output = argv[argv.index('-o') + 1]
        depfile = argv[argv.index('-MF') + 1]
        rules += [f'rule compile{index}', '  command = ' + shlex.join(argv).replace('$', '$$'),
                  '  depfile = ' + escaped(depfile), '  deps = gcc',
                  f'  description = CXX {relative}',
                  f'build {escaped(output)}: compile{index} {escaped(frozen)}']
        outputs.append(output)
    rules += ['rule link', '  command = ' + shlex.join(manifest['link_arguments']).replace('$', '$$'),
              '  description = LINK production UI',
              'build arcium_command_bar_studio: link ' + ' '.join(map(escaped, outputs)),
              'default arcium_command_bar_studio']
    graph = ('\n'.join(rules) + '\n').encode()
    path = objects / (hashlib.sha256(graph).hexdigest() + '.ninja')
    write(path, graph)
    return path, {relative: value[0] for relative, value in sources.items()}


def validate_external_includes(manifest, source_hashes):
    verified_path = SDK / 'verified-external-sources.json'
    verified = json.loads(verified_path.read_text()) if verified_path.exists() else {}
    # Older verification caches did not check local headers.
    previous = verified.get('complete-closure-v1', {})
    # Header additions or symlink changes can alter include search even when the
    # translation unit did not change. Ordinary writes to existing object files
    # do not change directory stamps, so warm no-op builds keep their cache.
    tree = []
    source_root = SDK / 'src'
    for directory, folders, files in os.walk(source_root):
        path = Path(directory); stat = path.stat()
        tree.append((str(path.relative_to(source_root)), stat.st_mtime_ns, stat.st_ctime_ns))
        tree.extend((str((path / name).relative_to(source_root)), os.readlink(path / name))
                    for name in folders + files if (path / name).is_symlink())
    tree_hash = hashlib.sha256(json.dumps(sorted(tree)).encode()).hexdigest()
    verified = previous.get('sources', {}) if previous.get('include_tree') == tree_hash else {}
    out = SDK / 'src/out/Default'; commands = []
    for entry in manifest['compile_commands']:
        argv = shlex.split(entry['command'].removeprefix('sccache '))
        original = argv[argv.index('-c') + 1]
        relative = str(Path(os.path.normpath(out / original)).relative_to(SDK / 'src'))
        identity = source_hashes[relative]
        if verified.get(relative) == identity: continue
        frozen = SDK / 'source-generations' / identity / Path(relative).name
        argv[argv.index('-c') + 1] = str(frozen)
        argv += ['-iquote', str((SDK / 'src' / relative).parent)]
        commands.append({'command': shlex.join(argv)})
    if commands:
        found = system_dependencies(commands, out, [Path(root) for root in manifest['system_sdks']],
                                    include_linker=False, captured_local=manifest['frozen_hashes'])
        introduced = set(found) - set(manifest['system_dependency_hashes'])
        if introduced:
            raise RuntimeError('New external SDK dependency requires a matching capture: ' + sorted(introduced)[0])
        write(verified_path, (json.dumps({'complete-closure-v1': {'sources': source_hashes, 'include_tree': tree_hash}}, sort_keys=True) + '\n').encode())


def build(jobs=6, keep_edits=False, source_root=None, experiments=None):
    global ROOT
    if not (SDK / 'manifest.json').exists(): raise RuntimeError('Capture the native SDK first; see README')
    previous_root = ROOT
    if source_root: ROOT = source_root
    try:
        validate()
        if not keep_edits: sync()
    finally:
        ROOT = previous_root
    manifest = json.loads((SDK / 'manifest.json').read_text())
    graph, source_hashes = frozen_source_graph(manifest, experiments)
    validate_external_includes(manifest, source_hashes)
    start = time.monotonic()
    run([SDK / 'ninja', '-f', graph, '-j', str(jobs)], cwd=SDK / 'src/out/Default')
    elapsed = time.monotonic() - start
    # Catch a frozen-header/library/SDK edit that arrived while the compiler ran.
    previous_root = ROOT
    if source_root: ROOT = source_root
    try:
        validate()
        validate_external_includes(manifest, source_hashes)
    finally:
        ROOT = previous_root
    record = {'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'build_seconds': round(elapsed, 3), 'jobs': jobs}
    with (SDK / 'timings.jsonl').open('a') as log: log.write(json.dumps(record) + '\n')
    write(SDK / 'last-build-sources.json', (json.dumps(source_hashes, sort_keys=True) + '\n').encode())
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
