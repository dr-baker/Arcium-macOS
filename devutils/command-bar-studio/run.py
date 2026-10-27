#!/usr/bin/env python3
"""Build and launch only the standalone Command Bar Studio."""
import argparse
import hashlib
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
BUILD = LAB / '.build'


def command(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def swift(action, jobs):
    env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(BUILD / 'module-cache'),
               SWIFTPM_MODULECACHE_OVERRIDE=str(BUILD / 'module-cache'))
    return command(['swift', action, '--package-path', LAB, '--scratch-path', BUILD / 'swift',
                    '--cache-path', BUILD / 'cache', '--config-path', BUILD / 'config',
                    '--security-path', BUILD / 'security', '--disable-sandbox', '-j', str(jobs)], env=env)


def prepare():
    command([sys.executable, LAB / 'prepare.py'])
    command([sys.executable, ROOT / 'devutils/glass-lab/prepare.py'])


def output_directory():
    # SwiftPM's debug symlink resolves the host triple without guessing it.
    return (BUILD / 'swift/debug').resolve(strict=True)


def macho_relocate(path, framework=False):
    listing = command(['otool', '-L', path], capture_output=True, text=True).stdout
    for line in listing.splitlines()[1:]:
        dependency = line.strip().split(' (')[0]
        if dependency.endswith('/libArciumSettingsUI.dylib') and not dependency.startswith('@rpath/'):
            command(['install_name_tool', '-change', dependency, '@rpath/libArciumSettingsUI.dylib', path])
    if framework:
        command(['install_name_tool', '-id', '@rpath/libArciumSettingsUI.dylib', path])
    load = command(['otool', '-l', path], capture_output=True, text=True).stdout.splitlines()
    rpaths = [load[i + 2].strip().split('path ', 1)[1].split(' (offset')[0]
              for i, line in enumerate(load) if line.strip() == 'cmd LC_RPATH']
    for rpath in rpaths:
        if rpath.startswith('/') and not rpath.startswith(('/usr/lib', '/System/')):
            command(['install_name_tool', '-delete_rpath', rpath, path])
    wanted = '@loader_path' if framework else '@executable_path/../Frameworks'
    if wanted not in rpaths:
        command(['install_name_tool', '-add_rpath', wanted, path])


def package():
    output = output_directory()
    binary = output / 'ArciumCommandBarStudio'
    dylib = output / 'libArciumSettingsUI.dylib'
    digest = hashlib.sha256(binary.read_bytes() + dylib.read_bytes() + Path(__file__).read_bytes())
    for bundle in sorted(output.glob('*.bundle')):
        for file in sorted(bundle.rglob('*')):
            if file.is_file():
                digest.update(str(file.relative_to(output)).encode()); digest.update(file.read_bytes())
    identity = digest.hexdigest()[:16]
    app = BUILD / 'apps' / identity / 'Arcium Command Bar Studio.app'
    if not app.exists():
        # Finish signing before publishing the immutable bundle path.
        temporary = app.parent / 'Packaging.app'
        if temporary.exists(): shutil.rmtree(temporary)
        macos = temporary / 'Contents/MacOS'; macos.mkdir(parents=True)
        frameworks = temporary / 'Contents/Frameworks'; frameworks.mkdir()
        resources = temporary / 'Contents/Resources'; resources.mkdir()
        shutil.copy2(binary, macos / binary.name); shutil.copy2(dylib, frameworks / dylib.name)
        for bundle in output.glob('*.bundle'):
            shutil.copytree(bundle, resources / bundle.name)
        info = {'CFBundleIdentifier': 'org.arcium.CommandBarStudio', 'CFBundleName': 'Command Bar Studio',
                'CFBundleExecutable': binary.name, 'CFBundlePackageType': 'APPL',
                'CFBundleShortVersionString': '1.0', 'CFBundleVersion': '1',
                'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '26.0'}
        (temporary / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        macho_relocate(macos / binary.name)
        macho_relocate(frameworks / dylib.name, framework=True)
        command(['codesign', '--force', '--sign', '-', frameworks / dylib.name])
        command(['codesign', '--force', '--sign', '-', temporary])
        command(['codesign', '--verify', '--strict', temporary])
        temporary.rename(app)
    latest = BUILD / 'Arcium Command Bar Studio.app'
    latest.unlink(missing_ok=True); latest.symlink_to(app.relative_to(BUILD))
    return app


def launch(app, extra_args=(), before_replace=None, writer_lease=None):
    state = BUILD / 'running.json'
    executable = app / 'Contents/MacOS/ArciumCommandBarStudio'
    old = json.loads(state.read_text()) if state.exists() else None
    ready = BUILD / 'launch-ready.json'
    ready.unlink(missing_ok=True)
    startup_started = time.monotonic()
    process = None
    committed = False
    try:
        with (BUILD / 'application.log').open('ab') as log:
            process = subprocess.Popen([str(executable), '--ready-file', str(ready), *map(str, extra_args)], stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=log, start_new_session=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'New Studio exited with {process.returncode}; previous app was left open. See {BUILD / "application.log"}')
            if ready.exists():
                readiness = json.loads(ready.read_text())
                if readiness == {'pid': process.pid, 'bundle': str(app)}: break
            time.sleep(.1)
        else:
            raise RuntimeError('New Studio did not become ready; previous app was left open.')
        if before_replace: before_replace()
        if old:
            if before_replace: before_replace()
            try:
                command([executable, '--quit-owned', str(old['pid']), old['executable']])
            except subprocess.CalledProcessError:
                raise RuntimeError('Previous Studio could not quit normally; replacement was closed.')
        (BUILD / 'last-launch-timing.json').write_text(json.dumps({'ready_seconds': time.monotonic() - startup_started, 'readiness': 'native compositor presentation callback for native host'}))
        if writer_lease:
            pending = Path(str(writer_lease) + '.pending')
            pending.write_text(str(process.pid)); pending.replace(writer_lease)
        state.write_text(json.dumps({'pid': process.pid, 'executable': str(executable)}, indent=2) + '\n')
        committed = True
        print(f'Command Bar Studio PID {process.pid}\n{app}')
    finally:
        # A new session does not receive the launcher's Ctrl-C. Retain ownership
        # through readiness and publication, then normally close any candidate
        # whose handoff did not finish. Never quit the previous app here.
        if process is not None and not committed and process.poll() is None:
            command([executable, '--quit-owned', str(process.pid), str(executable)])


def build(jobs):
    start = time.monotonic()
    prepare(); swift('build', jobs)
    compiled = time.monotonic()
    app = package()
    elapsed = time.monotonic() - start
    metric = {'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'prepare_build_seconds': round(compiled - start, 3),
              'total_seconds': round(elapsed, 3), 'app': str(app)}
    with (BUILD / 'timings.jsonl').open('a') as log: log.write(json.dumps(metric) + '\n')
    print(f'Prepare + Swift build: {metric["prepare_build_seconds"]:.2f}s; with signed packaging: {elapsed:.2f}s')
    return app


def watch_files():
    paths = [p for p in (LAB / 'Sources').rglob('*.swift') if p.name != 'ProductionContract.swift']
    paths += [LAB / name for name in ('prepare.py', 'run.py', 'Package.swift')]
    paths += [p for p in (ROOT / 'devutils/glass-lab/Sources/GlassNative').rglob('*') if p.is_file()]
    for repo in (ROOT, ROOT / 'helium-chromium'):
        paths.append(repo / 'patches/series')
    manifest = BUILD / 'production-manifest.json'
    if manifest.exists():
        paths += [ROOT / owner['path'] for owner in json.loads(manifest.read_text())['owners']]
    paths += [ROOT / 'patches/personal/arcium-surface-roles-macos.patch',
              ROOT / 'devutils/glass-lab/prepare.py', ROOT / 'devutils/glass-lab/Package.swift']
    for repo, mapping in ((ROOT, 'resources/platform_resources.txt'),
                          (ROOT / 'helium-chromium', 'resources/helium_resources.txt')):
        file = repo / mapping
        paths.append(file)
        for raw in file.read_text().splitlines():
            if not raw.strip() or raw.lstrip().startswith('#'): continue
            source, destination = raw.split()
            if destination.startswith('chrome/browser/ui/cocoa/arcium_settings_swift/'):
                paths.append(repo / 'resources' / source)
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=['run', 'build', 'test', 'watch'], default='run')
    parser.add_argument('--jobs', type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 16: parser.error('--jobs must be 1...16')
    if args.action == 'test':
        command([sys.executable, '-m', 'unittest', 'discover', '-s', str(LAB / 'python-tests')])
        prepare(); swift('test', args.jobs); return
    app = build(args.jobs)
    if args.action == 'build': print(app); return
    launch(app)
    if args.action != 'watch': return
    print('Watching Studio source and production settings patches. Ctrl-C stops watching and leaves Studio open.')
    last = watch_files()
    while True:
        time.sleep(.5)
        current = watch_files()
        if current == last: continue
        time.sleep(.3)
        current = watch_files()
        runner = str(LAB / 'run.py')
        if current.get(runner) != last.get(runner):
            os.execv(sys.executable, [sys.executable, str(LAB / 'run.py'), 'watch', '--jobs', str(args.jobs)])
        attempted = watch_files()
        try: launch(build(args.jobs))
        except (subprocess.CalledProcessError, RuntimeError) as error: print(f'Build failed; current app remains open: {error}', file=sys.stderr)
        # Saves during compilation remain pending, including after a failed build.
        last = attempted


if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: pass
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(error, file=sys.stderr); sys.exit(1)
