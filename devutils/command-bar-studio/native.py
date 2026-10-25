#!/usr/bin/env python3
"""Build/package the real Views renderer, or launch its independent Studio app."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
STATE = LAB / '.build/native'


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


def package(build_dir=None, source_app=None, settings_output=None, executable_override=None):
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
        info = {'CFBundleIdentifier': 'org.arcium.CommandBarStudioNative',
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
    (STATE / 'latest.json').write_text(json.dumps({'app': str(app)}, indent=2) + '\n')
    print(app)
    return app


def launch(app):
    runner = runner_module()
    runner.BUILD = STATE
    runner.launch(app)


def latest_app():
    latest = STATE / 'latest.json'
    if not latest.exists(): raise RuntimeError('Native Studio is not packaged. See README for the one-time focused build. Run "studio bootstrap" while owning the build lane.')
    return Path(json.loads(latest.read_text())['app'])


def controls(launch_app=True):
    source_app = latest_app()
    start = time.monotonic()
    command([sys.executable, LAB / 'prepare.py', '--settings-only'])
    cache = LAB / '.build'
    env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(cache / 'module-cache'),
               SWIFTPM_MODULECACHE_OVERRIDE=str(cache / 'module-cache'))
    command(['swift', 'build', '--package-path', cache / 'ProductionSettings',
             '--scratch-path', cache / 'native-settings', '--cache-path', cache / 'cache',
             '--config-path', cache / 'config', '--security-path', cache / 'security',
             '--disable-sandbox', '-j', '6', '--product', 'ArciumSettingsUI'], env=env)
    app = package(source_app=source_app, settings_output=(cache / 'native-settings/debug').resolve(strict=True))
    print(f'Controls build + native packaging: {time.monotonic() - start:.2f}s')
    if launch_app: launch(app)


def iterate(jobs, keep_edits=False, launch_app=True):
    import sdk
    start = time.monotonic()
    executable = sdk.build(jobs, keep_edits)
    app = package(source_app=latest_app(), executable_override=executable)
    elapsed = time.monotonic() - start
    with (STATE / 'timings.jsonl').open('a') as log:
        log.write(json.dumps({'total_seconds': round(elapsed, 3), 'app': str(app)}) + '\n')
    print(f'Actual renderer build + signed packaging: {elapsed:.2f}s')
    if launch_app: launch(app)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'build', 'bootstrap', 'capture', 'package', 'controls', 'launch', 'test'], nargs='?', default='run')
    parser.add_argument('--build-dir', type=Path, default=Path(os.environ['HELIUM_BUILD_DIR']) if os.environ.get('HELIUM_BUILD_DIR') else None)
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--keep-edits', action='store_true')
    parser.add_argument('--no-launch', action='store_true', help='Package controls without replacing the running app')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 13: parser.error('--jobs must be 1...13')
    if args.action == 'test':
        app = iterate(args.jobs, args.keep_edits, launch_app=False)
        for close_mode in ('done', 'window', 'quit'):
            report = STATE / f'interaction-checks-{close_mode}.json'
            report.unlink(missing_ok=True)
            command([app / 'Contents/MacOS/ArciumCommandBarStudio', '--interaction-check-report=' + str(report),
                     '--interaction-close=' + close_mode], timeout=30)
            result = json.loads(report.read_text())
            if not result.get('passed'): raise RuntimeError(f'Native interaction checks failed: {result}')
            print(json.dumps(result, indent=2))
        return
    if args.action == 'controls': controls(launch_app=not args.no_launch); return
    if args.action in ('run', 'build'):
        iterate(args.jobs, args.keep_edits, launch_app=args.action == 'run'); return
    if args.action == 'capture':
        if not args.build_dir: parser.error('--build-dir or HELIUM_BUILD_DIR required')
        import sdk
        sdk.export(args.build_dir / 'src')
        executable = sdk.build(args.jobs)
        package(args.build_dir, executable_override=executable); return
    if args.action == 'bootstrap':
        tooling(['build', '--daily', 'arcium_command_bar_studio'])
        # Packaging keeps the same durable reservation and verifies its owner.
        tooling(['lane', 'exec', '--', sys.executable, __file__, 'capture'])
        return
    if args.action == 'package':
        if not args.build_dir: parser.error('--build-dir or HELIUM_BUILD_DIR is required')
        package(args.build_dir); return
    launch(latest_app())


if __name__ == '__main__':
    try: main()
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(error, file=sys.stderr); sys.exit(1)
