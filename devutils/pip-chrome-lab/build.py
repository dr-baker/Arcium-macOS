#!/usr/bin/env python3
"""Compile the real PiP AppKit controls without Chromium or shared output."""
from pathlib import Path
import argparse
import plistlib
import shutil
import subprocess

root = Path(__file__).resolve().parent
repo = root.parents[1]
p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, help='Private authoring projection include root')
p.add_argument('--image', type=Path)
p.add_argument('--run', action='store_true')
p.add_argument('--test', action='store_true')
a = p.parse_args()
build = root / '.build'
source = a.source
if source is None:
    source = build / 'source'
    patch = (repo / 'patches/personal/arcium-pip-native-controls-macos.patch').read_text()
    for block in patch.split('Index: ')[1:]:
        lines = block.splitlines()
        path = lines[0]
        if '--- /dev/null' not in lines or not path.startswith('src/'):
            continue
        body = '\n'.join(line[1:] for line in lines
                         if line.startswith('+') and not line.startswith('+++')) + '\n'
        target = source / path[4:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
app = build / 'Arcium PiP Controls Lab.app'
exe = build / 'Verify' if a.test else app / 'Contents/MacOS/Arcium PiP Controls Lab'
if not a.test:
    processes = subprocess.check_output(['/bin/ps', '-axo', 'comm='], text=True).splitlines()
    if str(exe) in (line.strip() for line in processes):
        raise SystemExit('Quit the running controls lab before replacing its executable.')
exe.parent.mkdir(parents=True, exist_ok=True)
if not a.test:
    resources = app / 'Contents/Resources'
    resources.mkdir(parents=True, exist_ok=True)
    if a.image:
        shutil.copy2(a.image, resources / 'reference.png')
overlay = source / 'chrome/browser/ui/views/overlay'
cmd = ['/usr/bin/clang++', '-std=c++20', '-fobjc-arc', '-O2', '-Wall', '-Wextra',
       '-Wno-unused-parameter', '-I' + str(root / 'shims'), '-I' + str(source),
       '-I' + str(overlay), str(root / ('Verify.mm' if a.test else 'Host.mm')),
       '-framework', 'Cocoa', '-framework', 'QuartzCore', '-framework', 'AVFoundation',
       '-framework', 'CoreMedia', '-o', str(exe)]
subprocess.run(cmd, check=True)
if not a.test:
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleName': 'Arcium PiP Controls Lab',
        'CFBundleDisplayName': 'Arcium PiP Controls Lab',
        'CFBundleExecutable': exe.name,
        'CFBundleIdentifier': 'dev.arcium.pip-controls-lab',
        'CFBundlePackageType': 'APPL',
        'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
        'LSMinimumSystemVersion': '14.0',
    }))
subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-',
                str(exe if a.test else app)], check=True)
if a.test:
    subprocess.run([str(exe)], check=True)
elif a.run:
    subprocess.run(['/usr/bin/open', '-n', str(app)], check=True)
print(exe if a.test else app)
