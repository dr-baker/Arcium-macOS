#!/usr/bin/env python3
"""Run the focused browser comparison with the packaged production glass bridge."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def material_runtime(source, destination):
    """The flat test executable has no app-bundle COPY_BUNDLE_DATA actions."""
    expected = sha(source)
    created_directory = not destination.parent.exists()
    created_file = False
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file() or sha(destination) != expected:
            raise RuntimeError('Preserve conflicting browser-test runtime: ' + str(destination))
    else:
        destination.parent.mkdir(exist_ok=True)
        # Exclusive creation preserves any unexpected writer's file.
        with destination.open('xb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
        created_file = True
    try:
        if sha(destination) != expected: raise RuntimeError('Material runtime changed before launch')
        yield {'source': str(source), 'destination': str(destination), 'sha256': expected,
               'created_file': created_file}
    finally:
        if created_file:
            if destination.is_symlink() or not destination.is_file() or sha(destination) != expected:
                raise RuntimeError('Preserve changed browser-test runtime for inspection: ' + str(destination))
            destination.unlink()
        if created_directory:
            destination.parent.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Completed focused Chromium output directory')
    parser.add_argument('--browser-app', type=Path, required=True, help='Matching completed browser bundle; never guess among old Dev apps')
    parser.add_argument('--evidence', type=Path, required=True, help='New directory for captures, logs and provenance')
    args = parser.parse_args()
    output = args.output.resolve(strict=True)
    evidence = args.evidence.resolve(); evidence.mkdir(parents=True, exist_ok=False)
    library = args.browser_app.resolve(strict=True) / 'Contents/Frameworks/libArciumSettingsUI.dylib'
    if not library.is_relative_to(output): raise RuntimeError('Browser fixture must use this completed output bundle')
    exports = subprocess.run(['nm', '-gU', str(library)], check=True, capture_output=True, text=True).stdout
    for symbol in ('_ArciumPublicGlassCreate', '_ArciumPublicGlassUpdate'):
        if not any(line.split()[-1] == symbol for line in exports.splitlines() if line.split()):
            raise RuntimeError('Production material library lacks ' + symbol)
    executable = output / 'arcium_feature_settings_browser_tests'
    report = {'executable': str(executable), 'executable_sha256': sha(executable)}
    try:
        with material_runtime(library, output / 'Frameworks/libArciumSettingsUI.dylib') as runtime:
            report['material_runtime'] = runtime
            command = [str(executable), '--gtest_filter=ArciumCommandWorkshopBrowserTest.*',
                       '--test-launcher-jobs=1', '--test-launcher-retry-limit=0',
                       '--test-launcher-timeout=120000',
                       '--test-launcher-summary-output=' + str(evidence / 'summary.json'),
                       '--workshop-check-dir=' + str(evidence / 'captures')]
            report['command'] = command
            with (evidence / 'browser.log').open('w') as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            report['exit_code'] = result.returncode
    finally:
        (evidence / 'runtime.json').write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(result.returncode)


if __name__ == '__main__': main()
