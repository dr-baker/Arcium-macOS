#!/usr/bin/env python3
"""Stage a signed browser, drag-to-Applications DMG and notarization archive."""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True


def capture(*argv: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(argv, cwd=cwd, text=True).strip()


def run(*argv: str, env: dict[str, str] | None = None) -> None:
    print(shlex.join(argv), flush=True)
    subprocess.run(argv, check=True, env=env)


def load_plist(path: Path) -> dict:
    with path.open('rb') as handle:
        return plistlib.load(handle)


def write_plist(path: Path, value: dict) -> None:
    with path.open('xb') as handle:
        plistlib.dump(value, handle, fmt=plistlib.FMT_XML)


def tracked_clean(repo: Path) -> bool:
    result = subprocess.run(
        ['git', '-C', str(repo), 'diff', '--quiet', 'HEAD', '--ignore-submodules=untracked'],
        check=False,
    )
    if result.returncode > 1:
        raise RuntimeError(f'could not inspect tracked source state: {repo}')
    return result.returncode == 0


def verify_credits(out: Path) -> None:
    """Reject component builds that still ship Chromium's sample credits."""
    credits = out / 'gen/components/resources/about_credits.html'
    try:
        text = credits.read_text(encoding='utf-8')
    except OSError as error:
        raise RuntimeError('build full credits before packaging the preview') from error
    if ('generate_about_credits=true' in text or
            any(notice not in text for notice in
                ('Helium', 'Chromium', 'GNU GENERAL PUBLIC LICENSE'))):
        raise RuntimeError('preview credits are incomplete; set generate_about_credits=true '
                           'and rebuild chrome before packaging')


def archive_browser(browser: Path, archive: Path, identity: str, team_id: str) -> None:
    """Archive the browser itself, so Xcode notarizes the drag-install payload."""
    from he import apps

    archived_app = archive / 'Products/Applications/Arcium.app'
    archived_app.parent.mkdir(parents=True, exist_ok=False)
    apps.copy_app(browser, archived_app)
    apps.verify_signature(archived_app)
    info = load_plist(archived_app / 'Contents/Info.plist')
    archs = capture('/usr/bin/lipo', '-archs', str(apps.executable(archived_app))).split()
    write_plist(archive / 'Info.plist', {
        'ArchiveVersion': 2,
        'CreationDate': datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        'Name': 'Arcium',
        'SchemeName': 'Arcium',
        'ApplicationProperties': {
            'ApplicationPath': 'Applications/Arcium.app',
            'Architectures': archs,
            'CFBundleIdentifier': info['CFBundleIdentifier'],
            'CFBundleShortVersionString': info['CFBundleShortVersionString'],
            'CFBundleVersion': info['CFBundleVersion'],
            'SigningIdentity': identity,
            'Team': team_id,
        },
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--identity')
    parser.add_argument('--team-id', default='45W5CFCVQF')
    parser.add_argument('--stage', action='store_true', help='Copy and sign locally; no upload or installation')
    parser.add_argument('--inside-lock', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    out = args.out_dir.expanduser().resolve()
    destination_input = args.destination.expanduser()
    if destination_input.exists() or destination_input.is_symlink():
        parser.error('destination must be new; existing output is never overwritten')
    destination = destination_input.resolve()
    if destination == out or out in destination.parents:
        parser.error('destination must be outside the shared output directory')
    if destination == Path('/Applications') or Path('/Applications') in destination.parents:
        parser.error('this tool stages release artifacts; choose a destination outside Applications')

    core = repo / 'helium-chromium'
    source_paths = [repo / 'devutils/arcium/install.py',
                    repo / 'devutils/package_preview.py',
                    repo / 'devutils/release_dmg.py',
                    repo / 'resources/dmg.json',
                    repo / 'resources/dmg-background.png',
                    repo / 'resources/dmg-background@2x.png',
                    repo / 'resources/preview/initial-preferences.json']
    for path in source_paths:
        if not path.is_file():
            parser.error(f'missing canonical packaging input: {path}')
        capture('git', '-C', str(repo), 'ls-files', '--error-unmatch',
                str(path.relative_to(repo)))
    if out.name != 'Default' or out.parent.name != 'out' or out.parent.parent.name != 'src':
        parser.error('expected BUILD_DIR/src/out/Default')
    build_dir = out.parent.parent.parent
    tree_entry = capture('git', '-C', str(repo), 'ls-tree', 'HEAD', 'helium-chromium').split()
    if len(tree_entry) < 3 or tree_entry[0] != '160000':
        parser.error('canonical source must retain its core gitlink')
    outer_commit = capture('git', '-C', str(repo), 'rev-parse', 'HEAD')
    core_commit = capture('git', '-C', str(core), 'rev-parse', 'HEAD')
    if tree_entry[2] != core_commit:
        parser.error('checked-out core differs from the committed outer gitlink')
    if not tracked_clean(repo) or not tracked_clean(core):
        parser.error('commit tracked canonical changes before recording release provenance')

    plan = {
        'source': str(out / 'Helium.app'),
        'browser': str(destination / 'browser/Arcium.app'),
        'disk_image': str(destination / 'Arcium.dmg'),
        'archive': str(destination / 'Arcium-Preview.xcarchive'),
        'macos_commit': outer_commit,
        'core_commit': core_commit,
        'source_layout': 'Canonical core gitlink retained; no source flattening',
        'uploads_or_installation': False,
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.stage:
        print('Plan only. Add --stage after reviewing the script and completing the daily chrome build.')
        return 0

    sys.path.insert(0, str(repo / 'devutils'))
    from he import apps, builds, catalog, quilt, timestamps
    from he.common import make_paths
    from he.lock import run_locked
    from arcium.bundle import signing_identity, verify_identity
    from arcium.install import package
    from release_dmg import create_disk_image

    if not args.inside_lock:
        argv = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--inside-lock']
        return run_locked(build_dir / '.arcium/lane.lock', argv, label='package-release')

    paths = make_paths(repo, build_dir, 'daily')
    if problems := catalog.drift(paths):
        parser.error('source differs from the applied build catalog: ' + '; '.join(problems))
    if timestamps.pending(paths) or quilt.applied(paths.src) != quilt.read_list(paths.catalog / 'series.merged'):
        parser.error('complete the guarded patch replay before packaging')
    receipt = builds.require_completed(out, 'daily')
    verify_credits(out)
    identity = args.identity or signing_identity()
    if not identity.startswith('Developer ID Application:'):
        parser.error('a Developer ID Application identity is required')
    destination.mkdir(parents=True, exist_ok=False)
    browser = destination / 'browser/Arcium.app'
    packaged = package(out, browser, identity)
    verify_identity(browser)
    if builds.require_completed(out, 'daily') != receipt:
        raise RuntimeError('shared output changed during packaging')

    create_disk_image(browser, destination / 'Arcium.dmg', identity)

    archive = destination / 'Arcium-Preview.xcarchive'
    archive_browser(browser, archive, identity, args.team_id)
    options = destination / 'NotarizationOptions.plist'
    write_plist(options, {
        'destination': 'upload',
        'method': 'developer-id',
        'manageAppVersionAndBuildNumber': False,
        'signingStyle': 'manual',
        'signingCertificate': identity,
        'teamID': args.team_id,
    })
    provenance = {**plan, 'build': receipt, 'packaging': packaged, 'signing_identity': identity,
                  'archive_signature_verified': True, 'notarized': False,
                  'browser_sha256': capture('/usr/bin/shasum', '-a', '256', str(apps.executable(browser))).split()[0]}
    (destination / 'packaging-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')

    export = destination / 'notarized'
    upload_command = ['/usr/bin/xcodebuild', '-exportArchive', '-archivePath', str(archive),
                      '-exportOptionsPlist', str(options), '-exportPath', str(destination / 'upload-export')]
    export_commands = [
        ['/usr/bin/xcodebuild', '-exportNotarizedApp', '-archivePath', str(archive), '-exportPath', str(export)],
        ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(export / 'Arcium.app')],
        ['/usr/bin/xcrun', 'stapler', 'validate', str(export / 'Arcium.app')],
        [sys.executable, str(repo / 'devutils/release_dmg.py'),
         '--app', str(export / 'Arcium.app'), '--destination', str(export / 'Arcium.dmg'),
         '--identity', identity],
    ]
    upload_script = destination / 'upload-notarization.sh'
    upload_script.write_text('#!/bin/bash\nset -euo pipefail\n' + shlex.join(upload_command) + '\n')
    export_script = destination / 'export-notarized.sh'
    export_script.write_text('#!/bin/bash\nset -euo pipefail\n' + '\n'.join(shlex.join(command) for command in export_commands) + '\n')
    print(f'Staged only. Review and invoke upload separately: {upload_script}')
    print(f'After Apple processing is complete, invoke separately: {export_script}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
