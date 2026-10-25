#!/usr/bin/env python3
"""Build/package the real Views renderer, or launch its independent Studio app."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
STATE_ROOT = LAB / '.build/native'
STATE = STATE_ROOT
INSTANCE = 'user'


def command(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def tooling(arguments):
    canonical = Path(os.environ.get('HELIUM_TOOLING_ROOT', '/Users/daniel/Developer/Helium/helium-macos'))
    env = dict(os.environ, HELIUM_DEV_WORKTREE=str(ROOT))
    command(['/bin/zsh', '-c', 'source "$1/dev.sh"; shift; he agent "$@"', 'studio', canonical, *arguments], env=env)


def clone(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    command(['/bin/cp', '-cR', source, destination])


def runner_module():
    spec = importlib.util.spec_from_file_location('studio_runner', LAB / 'run.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    return runner


def file_hash(path, cache):
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    stamp = [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    previous = cache.get(str(resolved), {})
    if previous.get('stamp') == stamp: return previous['hash']
    digest = hashlib.sha256()
    with resolved.open('rb') as source:
        while block := source.read(1024 * 1024): digest.update(block)
    value = digest.hexdigest(); cache[str(resolved)] = {'stamp': stamp, 'hash': value}
    return value


def package(build_dir=None, source_app=None, settings_output=None, executable_override=None,
            publish=True, generation=None, experimental=False):
    if source_app:
        executable = source_app / 'Contents/MacOS/ArciumCommandBarStudio'
        original = source_app / 'Contents/Frameworks/ArciumStudioRuntime.framework'
        pak = source_app / 'Contents/Resources/ui_test.pak'
        resource_bundle = source_app / 'Contents/Resources/ArciumSettingsUI_ArciumSettingsUI.bundle'
    else:
        output = build_dir / 'src/out/Default'
        executable = output / 'arcium_command_bar_studio'
        if not executable.is_file(): raise RuntimeError(f'Build the arcium_command_bar_studio target first: {executable}')
        frameworks = list(output.glob('*.framework'))
        if len(frameworks) != 1: raise RuntimeError(f'Expected one completed runtime framework, found {frameworks}')
        original = frameworks[0]
        pak = output / 'ui_test.pak'
        if not pak.exists(): pak = output / 'gen/ui/resources/ui_test.pak'
        staged = output / 'gen/chrome/browser/ui/cocoa/arcium_settings_swift/staged'
        resource_bundle = staged / 'ArciumSettingsUI_ArciumSettingsUI.bundle'
    if executable_override: executable = executable_override
    libraries = (original / 'Libraries').resolve()
    swift = source_app / 'Contents/Frameworks/libArciumSettingsUI.dylib' if source_app else staged / 'libArciumSettingsUI.dylib'
    if not swift.exists(): raise RuntimeError('Completed production Swift settings library missing')
    if not pak.exists(): raise RuntimeError('ui_test.pak missing from completed focused build')
    if settings_output:
        swift = settings_output / 'libArciumSettingsUI.dylib'
        resource_bundle = settings_output / 'ArciumSettingsUI_ArciumSettingsUI.bundle'
    STATE.mkdir(parents=True, exist_ok=True)
    cache_path = STATE / 'input-hashes.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(INSTANCE.encode())
    if generation: digest.update(generation.identity.encode())
    sdk_root = LAB / '.build/native-sdk'
    sdk_audit = sdk_root / 'audit/dynamic-library-closure.json'
    sdk_components = []
    if executable_override:
        expected = sdk_root / 'src/out/Default/arcium_command_bar_studio'
        if executable_override.resolve() != expected.resolve():
            raise RuntimeError('Runtime override must use the matching SDK-built executable')
        sdk_components = [sdk_root / 'src/out/Default' / Path(p).name
                          for p in json.loads(sdk_audit.read_text())['files']]
    elif not source_app:
        import sdk_audit as audit
        listing = command(['otool', '-L', executable], capture_output=True, text=True).stdout
        direct = [line.strip().split(' (')[0].removeprefix('@rpath/')
                  for line in listing.splitlines()[1:] if line.strip().startswith('@rpath/')]
        sdk_components = [Path(p) for p in audit.dylib_closure(output, direct)['files']]
    inputs = [('executable', executable), ('swift', swift), ('pak', pak)]
    inputs += [('sdk-component/' + p.name, p) for p in sdk_components]
    inputs += [('framework/' + str(p.relative_to(original)), p) for p in sorted(original.rglob('*'))]
    if not source_app:
        inputs += [('current-component/' + p.name, output / p.name)
                   for p in libraries.glob('*.dylib') if (output / p.name).is_file()]
    inputs += [('settings/' + str(p.relative_to(resource_bundle)), p) for p in sorted(resource_bundle.rglob('*'))]
    for name, path in inputs:
        if path.is_file():
            digest.update(name.encode())
            digest.update(file_hash(path, cache).encode())
    cache_path.write_text(json.dumps(cache) + '\n')
    identity = digest.hexdigest()[:16]
    app = STATE / 'apps' / identity / 'Arcium Command Bar Studio Native.app'
    if not app.exists():
        temporary = app.parent / 'Packaging.app'
        if temporary.exists(): shutil.rmtree(temporary)
        macos = temporary / 'Contents/MacOS'; macos.mkdir(parents=True)
        owned_frameworks = temporary / 'Contents/Frameworks'; owned_frameworks.mkdir()
        resources = temporary / 'Contents/Resources'; resources.mkdir()
        shutil.copy2(executable, macos / 'ArciumCommandBarStudio')
        runtime = owned_frameworks / 'ArciumStudioRuntime.framework'
        clone(original, runtime)
        # Chrome's component outputs can be symlinked outside its framework.
        # Resolve those into copied files, preserving only internal relative links.
        for link in sorted(runtime.rglob('*')):
            if not link.is_symlink(): continue
            target = link.resolve(strict=True)
            if target.is_relative_to(temporary.resolve()): continue
            link.unlink(); clone(target, link)
        if not source_app:
            # The focused target skips Chrome's COPY_BUNDLE_DATA actions.
            # Prefer each current linked component over an older bundle copy.
            for library in (runtime / 'Libraries').glob('*.dylib'):
                current = output / library.name
                if current.is_file(): shutil.copy2(current, library.resolve())
        for current in sdk_components:
            destination = runtime / 'Libraries' / current.name
            shutil.copy2(current, destination.resolve())
        shutil.copy2(swift, owned_frameworks / swift.name)
        if settings_output:
            # All entry points in this process resolve the same Swift build.
            runtime_swift = runtime / 'Libraries/libArciumSettingsUI.dylib'
            shutil.copy2(swift, runtime_swift.resolve())
            runner_module().macho_relocate(runtime_swift.resolve(), framework=True)
        runner_module().macho_relocate(owned_frameworks / swift.name, framework=True)
        shutil.copytree(resource_bundle, resources / resource_bundle.name, symlinks=False)
        shutil.copy2(pak, resources / 'ui_test.pak')
        source_record = sdk_root / 'last-build-sources.json'
        swift_record = LAB / '.build/production-manifest.json'
        provenance = {
            'schema': 1, 'component': 'command-bar', 'instance': INSTANCE,
            'generation': generation.identity if generation else None,
            'experimental': experimental,
            'renderer_sources': json.loads(source_record.read_text()) if source_record.exists() else {},
            'swift_sources': json.loads(swift_record.read_text()).get('files', {}) if swift_record.exists() else {},
            'executable_sha256': file_hash(executable, cache),
            'swift_sha256': file_hash(swift, cache),
        }
        (resources / 'UIWorkshopBuild.json').write_text(json.dumps(provenance, indent=2) + '\n')
        bundle_id = 'org.arcium.CommandBarStudioNative' + ('' if INSTANCE == 'user' else '.' + INSTANCE)
        info = {'CFBundleIdentifier': bundle_id,
                'CFBundleName': 'Command Bar Studio Native', 'CFBundleExecutable': 'ArciumCommandBarStudio',
                'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '1.0', 'CFBundleVersion': '1',
                'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '26.0'}
        (temporary / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        binary = macos / 'ArciumCommandBarStudio'
        load = command(['otool', '-l', binary], capture_output=True, text=True).stdout.splitlines()
        rpaths = [load[i + 2].strip().split('path ', 1)[1].split(' (offset')[0]
                  for i, line in enumerate(load) if line.strip() == 'cmd LC_RPATH']
        for path in rpaths:
            if path.startswith('/') and not path.startswith(('/System/', '/usr/lib/')):
                command(['install_name_tool', '-delete_rpath', path, binary])
        wanted = '@executable_path/../Frameworks/ArciumStudioRuntime.framework/Libraries'
        if wanted not in rpaths: command(['install_name_tool', '-add_rpath', wanted, binary])
        command(['codesign', '--force', '--sign', '-', owned_frameworks / swift.name])
        command(['codesign', '--force', '--deep', '--sign', '-', runtime])
        command(['codesign', '--force', '--sign', '-', temporary])
        command(['codesign', '--verify', '--deep', '--strict', temporary])
        temporary.rename(app)
    STATE.mkdir(parents=True, exist_ok=True)
    if publish:
        (STATE / 'latest.json').write_text(json.dumps({'app': str(app)}, indent=2) + '\n')
    print(app)
    return app


def launch(app, before_replace=None):
    runner = runner_module()
    runner.BUILD = STATE
    STATE.mkdir(parents=True, exist_ok=True)
    lease = STATE / 'scenario-writer'
    runner.launch(app, extra_args=('--scenario-file=' + str(STATE / 'scenario.json'),
                                  '--writer-lease=' + str(lease)),
                  before_replace=before_replace, writer_lease=lease)


def latest_app():
    latest = STATE / 'latest.json'
    if not latest.exists(): raise RuntimeError('Native Studio is not packaged. See README for the one-time focused build. Run "studio bootstrap" while owning the build lane.')
    return Path(json.loads(latest.read_text())['app'])


def runtime_template():
    # A new test/watch identity may copy the independent runtime, but never
    # adopts or launches the user's existing app instance.
    manifest_path = LAB / '.build/native-sdk/manifest.json'
    if manifest_path.exists():
        template = json.loads(manifest_path.read_text()).get('runtime_template')
        if template:
            if not Path(template).is_dir(): raise RuntimeError('Captured runtime template missing; preserve or refresh the SDK capture')
            expected = json.loads(manifest_path.read_text()).get('runtime_inputs')
            if expected is None:
                raise RuntimeError('SDK lacks pinned runtime resources; refresh the SDK capture')
            if runtime_inputs(Path(template)) != expected:
                raise RuntimeError('Captured runtime resources or symlink mappings changed; refresh the SDK capture')
            return Path(template)
        raise RuntimeError('SDK lacks a pinned runtime template; refresh the SDK capture')
    try:
        return latest_app()
    except RuntimeError:
        baseline = STATE_ROOT / 'latest.json'
        if INSTANCE == 'user' or not baseline.exists(): raise
        return Path(json.loads(baseline.read_text())['app'])


def runtime_inputs(app):
    """Pin the independent bundle, including resources and link destinations."""
    cache_path = STATE_ROOT / 'runtime-input-hashes.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    result = {}
    root = app.resolve(strict=True)
    for path in sorted(app.rglob('*')):
        name = str(path.relative_to(app))
        if path.is_symlink():
            if not path.resolve(strict=True).is_relative_to(root):
                raise RuntimeError('Runtime template has an external symlink: ' + name)
            result[name] = {'link': os.readlink(path)}
        elif path.is_file():
            result[name] = {'sha256': file_hash(path, cache)}
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache) + '\n')
    return result


def build_settings(jobs, source_root=None):
    arguments = [sys.executable, LAB / 'prepare.py', '--settings-only']
    if source_root: arguments += ['--source-root', source_root]
    command(arguments)
    cache = LAB / '.build'
    env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(cache / 'module-cache'),
               SWIFTPM_MODULECACHE_OVERRIDE=str(cache / 'module-cache'))
    command(['swift', 'build', '--package-path', cache / 'ProductionSettings',
             '--scratch-path', cache / 'native-settings', '--cache-path', cache / 'cache',
             '--config-path', cache / 'config', '--security-path', cache / 'security',
             '--disable-sandbox', '-j', str(jobs), '--product', 'ArciumSettingsUI'], env=env)
    return (cache / 'native-settings/debug').resolve(strict=True)


def controls(launch_app=True, jobs=6):
    # Controls and renderer must come from the same current production sources.
    return iterate(jobs, launch_app=launch_app)


def iterate(jobs, keep_edits=False, launch_app=True):
    import sdk
    import iteration
    with iteration.build_lock(STATE_ROOT):
        start = time.monotonic()
        extra = sdk.experiment_inputs() if keep_edits else None
        generation = iteration.capture(ROOT, STATE_ROOT / 'inputs', extra_files=extra) if extra else iteration.capture(ROOT, STATE_ROOT / 'inputs')
        options = {}
        if extra:
            options['experiments'] = {name.removeprefix('.sdk-experiments/'): (generation.root / name, generation.files[name])
                                      for name in extra}
        executable = sdk.build(jobs, keep_edits, source_root=generation.root, **options)
        settings_output = build_settings(jobs, source_root=generation.root)
        generation.require_current()
        app = package(source_app=runtime_template(), settings_output=settings_output,
                      executable_override=executable, publish=False,
                      generation=generation, experimental=keep_edits)
        runtime_template()  # Reject a resource change arriving during packaging.
        generation.require_current()
        if launch_app: launch(app, before_replace=generation.require_current)
        iteration.publish_latest(STATE, app, generation)
        elapsed = time.monotonic() - start
        with (STATE / 'timings.jsonl').open('a') as log:
            log.write(json.dumps({'total_seconds': round(elapsed, 3), 'app': str(app),
                                 'generation': generation.identity, 'experimental': keep_edits}) + '\n')
        print(f'Actual renderer build + signed packaging: {elapsed:.2f}s')
        return app


def watch(jobs, keep_edits, interval):
    import iteration, sdk
    previous = None; last_error = None
    print(f'Watching production UI inputs; isolated instance {INSTANCE}', flush=True)
    while True:
        current = None
        try:
            extra = sdk.experiment_inputs() if keep_edits else None
            current = iteration.stamps(ROOT, extra_files=extra)
            if current != previous:
                time.sleep(interval)
                if iteration.stamps(ROOT, extra_files=extra) != current: continue
                iterate(jobs, keep_edits)
                previous = current
            last_error = None
        except (RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as error:
            if str(error) != last_error:
                print(f'Iteration retained the previous app: {error}', file=sys.stderr, flush=True)
                last_error = str(error)
            # Retry only after another source change; malformed saves are routine.
            if current is not None: previous = current
        time.sleep(interval)


def main():
    global STATE, INSTANCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'build', 'bootstrap', 'capture', 'package', 'controls', 'launch', 'test', 'watch', 'scenario'], nargs='?', default='run')
    parser.add_argument('--build-dir', type=Path, default=Path(os.environ['HELIUM_BUILD_DIR']) if os.environ.get('HELIUM_BUILD_DIR') else None)
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--fixture', choices=['mixed', 'empty', 'long', 'streaming'], default='mixed')
    parser.add_argument('--scenario-file', type=Path, help='Load a tooling scenario without compiling')
    parser.add_argument('--keep-edits', action='store_true')
    parser.add_argument('--no-launch', action='store_true', help='Package controls without replacing the running app')
    parser.add_argument('--instance', help='Independent app/configuration identity; watch and test use separate defaults')
    parser.add_argument('--poll-interval', type=float, default=0.25)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 13: parser.error('--jobs must be 1...13')
    if not 0 < args.poll_interval <= 5: parser.error('--poll-interval must be >0 and <=5 seconds')
    INSTANCE = args.instance or {'watch': 'watch', 'test': 'validation'}.get(args.action, 'user')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', INSTANCE): parser.error('Invalid instance name')
    STATE = STATE_ROOT if INSTANCE == 'user' else STATE_ROOT / 'instances' / INSTANCE
    if args.action == 'scenario':
        STATE.mkdir(parents=True, exist_ok=True)
        document = {'schema': 'arcium-ui-workshop', 'version': 1, 'component': 'command-bar',
                    'fixture': args.fixture, 'query': '', 'scope': 'omni'}
        existing = STATE / 'scenario.json'
        if not args.scenario_file and existing.exists():
            document = json.loads(existing.read_text()); document['fixture'] = args.fixture
        if args.scenario_file:
            if args.scenario_file.stat().st_size > 1024 * 1024: raise RuntimeError('Scenario exceeds 1 MiB')
            document = json.loads(args.scenario_file.read_text())
            if document.get('schema') != 'arcium-ui-workshop' or document.get('version') != 1:
                raise RuntimeError('Unsupported scenario document')
        temporary = STATE / 'scenario.pending.json'
        temporary.write_text(json.dumps(document, indent=2) + '\n')
        temporary.replace(STATE / 'scenario.json')
        print(STATE / 'scenario.json')
        return
    if args.action == 'watch':
        try: watch(args.jobs, args.keep_edits, args.poll_interval)
        except KeyboardInterrupt: pass
        return
    if args.action == 'test':
        app = iterate(args.jobs, args.keep_edits, launch_app=False)
        for close_mode in ('done', 'window', 'quit'):
            report = STATE / f'interaction-checks-{close_mode}.json'
            report.unlink(missing_ok=True)
            with tempfile.TemporaryDirectory(prefix='scenario-check-', dir=STATE) as temporary:
                command([app / 'Contents/MacOS/ArciumCommandBarStudio', '--interaction-check-report=' + str(report),
                         '--interaction-close=' + close_mode, '--scenario-file=' + str(Path(temporary) / 'scenario.json')], timeout=30)
            result = json.loads(report.read_text())
            if not result.get('passed'): raise RuntimeError(f'Native interaction checks failed: {result}')
            print(json.dumps(result, indent=2))
        return
    if args.action == 'controls': controls(launch_app=not args.no_launch, jobs=args.jobs); return
    if args.action in ('run', 'build'):
        iterate(args.jobs, args.keep_edits, launch_app=args.action == 'run'); return
    if args.action == 'capture':
        if not args.build_dir: parser.error('--build-dir or HELIUM_BUILD_DIR required')
        import sdk, iteration
        with iteration.build_lock(STATE_ROOT):
            generation = iteration.capture(ROOT, STATE_ROOT / 'inputs')
            sdk.export(args.build_dir / 'src')
            generation.require_current()
            executable = sdk.build(args.jobs, source_root=generation.root)
            settings_output = build_settings(args.jobs, source_root=generation.root)
            generation.require_current()
            app = package(args.build_dir, executable_override=executable,
                          settings_output=settings_output, publish=False, generation=generation)
            generation.require_current()
            manifest_path = LAB / '.build/native-sdk/manifest.json'
            manifest = json.loads(manifest_path.read_text()); manifest['runtime_template'] = str(app)
            manifest['runtime_inputs'] = runtime_inputs(app)
            manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
            iteration.publish_latest(STATE, app, generation)
        return
    if args.action == 'bootstrap':
        tooling(['build', '--daily', 'arcium_command_bar_studio'])
        # Packaging keeps the same durable reservation and verifies its owner.
        tooling(['lane', 'exec', '--', sys.executable, __file__, 'capture'])
        return
    if args.action == 'package':
        if not args.build_dir: parser.error('--build-dir or HELIUM_BUILD_DIR is required')
        package(args.build_dir); return
    import iteration
    with iteration.build_lock(STATE_ROOT): launch(latest_app())


if __name__ == '__main__':
    try: main()
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(error, file=sys.stderr); sys.exit(1)
