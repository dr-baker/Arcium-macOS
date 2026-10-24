#!/usr/bin/env python3
"""Materialize the production settings package without a Chromium checkout."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
LAB = Path(__file__).resolve().parent
PREFIX = 'chrome/browser/ui/cocoa/arcium_settings_swift/'
PANEL = 'chrome/browser/ui/views/omnibox/arcium_command_panel.cc'
EXAMPLES = 'chrome/browser/ui/omnibox/arcium_command_example_session.h'
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def path_name(raw: str) -> str:
    for prefix in ('src.orig/', 'src/', 'a/', 'b/'):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def selected(path: str) -> bool:
    return path.startswith(PREFIX) or path in (PANEL, EXAMPLES)


def apply_patch(files: dict[str, list[str]], text: str, owner: str) -> set[str]:
    lines = text.splitlines()
    index = 0
    touched: set[str] = set()
    while index < len(lines):
        if not (lines[index].startswith('--- ') and index + 1 < len(lines)
                and lines[index + 1].startswith('+++ ')):
            index += 1
            continue
        old_path = shlex.split(lines[index][4:].split('\t')[0])[0]
        new_path = shlex.split(lines[index + 1][4:].split('\t')[0])[0]
        path = path_name(new_path if new_path != '/dev/null' else old_path)
        index += 2
        wanted = selected(path)
        content = list(files.get(path, []))
        cursor = 0
        shift = 0
        saw_hunk = False
        while index < len(lines):
            match = HUNK.match(lines[index])
            if not match:
                break
            old_start, old_count, _, new_count = match.groups()
            old_start, old_count, new_count = int(old_start), int(old_count or 1), int(new_count or 1)
            index += 1
            before: list[str] = []
            after: list[str] = []
            while len(before) < old_count or len(after) < new_count:
                if index >= len(lines):
                    raise ValueError(f'{owner}: incomplete hunk for {path}')
                line = lines[index]
                index += 1
                if line.startswith('\\ No newline'):
                    continue
                if not line or line[0] not in ' +-':
                    raise ValueError(f'{owner}: invalid hunk line for {path}')
                if line[0] in ' -': before.append(line[1:])
                if line[0] in ' +': after.append(line[1:])
            if index < len(lines) and lines[index].startswith('\\ No newline'):
                index += 1
            if not wanted:
                continue
            if path not in files and old_count:
                raise ValueError(f'{owner}: missing preimage for {path}; no Chromium source fallback')
            expected = (old_start if old_count == 0 else old_start - 1) + shift
            position = expected
            if position < cursor or content[position:position + old_count] != before:
                candidates = [i for i in range(cursor, len(content) - old_count + 1)
                              if content[i:i + old_count] == before]
                if len(candidates) != 1:
                    raise ValueError(f'{owner}: exact context not unique for {path}:{old_start}')
                position = candidates[0]
            content[position:position + old_count] = after
            shift += position - expected + new_count - old_count
            cursor = position + new_count
            saw_hunk = True
            files[path] = content
        if wanted and saw_hunk:
            touched.add(path)
            if new_path == '/dev/null': files.pop(path, None)
    return touched


def write_changed(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def materialize() -> dict:
    files: dict[str, list[str]] = {}
    owners = []
    for repo in (ROOT / 'helium-chromium', ROOT):
        for raw in (repo / 'patches/series').read_text().splitlines():
            name = raw.split('#')[0].strip()
            if not name:
                continue
            patch = repo / 'patches' / name
            text = patch.read_text()
            # Most of the catalog has no settings or preview files.
            if not any(p in text for p in (PREFIX, PANEL, EXAMPLES)):
                continue
            touched = apply_patch(files, text, str(patch.relative_to(ROOT)))
            if touched:
                owners.append({'path': str(patch.relative_to(ROOT)),
                               'sha256': hashlib.sha256(patch.read_bytes()).hexdigest()})
    package = LAB / '.build/ProductionSettings'
    outputs = {}
    for path, lines in files.items():
        if path.startswith(PREFIX):
            outputs[path[len(PREFIX):]] = ('\n'.join(lines) + '\n').encode()
    for repo, mapping in ((ROOT, 'resources/platform_resources.txt'),
                          (ROOT / 'helium-chromium', 'resources/helium_resources.txt')):
        for raw in (repo / mapping).read_text().splitlines():
            if not raw.strip() or raw.lstrip().startswith('#'):
                continue
            source, destination = raw.split()
            if destination.startswith(PREFIX):
                outputs[destination[len(PREFIX):]] = (repo / 'resources' / source).read_bytes()
    required = ('Package.swift', 'Sources/ArciumSettingsUI/ArciumSettingsUIController.swift',
                'Sources/ArciumSettingsUI/ArciumSettingsModels.swift', 'Vendor/SettingsUI/Package.swift',
                'Sources/ArciumSettingsUI/Resources/yellow-blue grain.json')
    if not all(p in outputs for p in required):
        raise ValueError('production settings package is incomplete')
    manifest_path = LAB / '.build/production-manifest.json'
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for relative, digest in old.get('files', {}).items():
        path = package / relative
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Generated production source was edited: {path}; preserve the edit before preparing again')
    for relative in old.get('files', {}):
        if relative not in outputs:
            (package / relative).unlink(missing_ok=True)
    for relative, data in outputs.items():
        write_changed(package / relative, data)
    panel = '\n'.join(files[PANEL]) + '\n'
    examples = '\n'.join(files[EXAMPLES]) + '\n'
    write_changed(LAB / '.build/production-command-panel.cc', panel.encode())
    write_changed(LAB / '.build/production-examples.h', examples.encode())
    rows = re.findall(r'return \{([\d., false tru-]+)\};', panel.split('ScopeGeometry GeometryForReveal', 1)[1].split('NOTREACHED()', 1)[0])
    if len(rows) != 6:
        raise ValueError('Reveal geometry changed: update the standalone renderer contract')
    geometry = []
    for row in rows:
        values = [v.strip() for v in row.split(',')]
        geometry.append(f'ScopeGeometry(restingRise: {values[0]}, revealedRise: {values[1]}, restingHeight: {values[2]}, padding: {values[3]}, hiddenIcons: {values[4]}, detent: {values[5]})')
    # Reject a changed light law rather than silently showing an old approximation.
    compact = re.sub(r'\s+', '', panel)
    expressions = ('radius_x=source.width()/2+softness', 'radius_y=source.height()+softness',
                   'power=source.width()*source.height()', '.48f*strength*power/(radius_x*radius_y)',
                   'matrix.postTranslate(center_x,source.y())',
                   'row_focus=.66f+.34f*scope_focus_animation_.GetCurrentValue()',
                   'selected=1.f+.30f*ScopeWeight(index)')
    missing = [e for e in expressions if e not in compact]
    if missing:
        raise ValueError(f'Production light law changed: update the standalone renderer contract ({missing})')
    constants = {name: int(value) for name, value in re.findall(r'constexpr int (k\w+) = (\d+);', panel)}
    titles = re.findall(r'\{u"([^"]+)", u"([^"]+)", u"([^"]+)", CommandPrimaryIcon::k(\w+), CommandActivity::k(\w+)\}', examples)
    if len(titles) != 8:
        raise ValueError('Production example data changed: update the standalone fixture contract')
    swift_string = lambda value: json.dumps(value, ensure_ascii=False)
    swift = '// Generated from production patches. Do not edit.\nimport Foundation\nenum ProductionContract {\n'
    swift += '    static let geometry: [ScopeGeometry] = [\n        ' + ',\n        '.join(geometry) + '\n    ]\n'
    for key in ('kSearchHeight', 'kRowHeight', 'kFooterHeight', 'kEmptyHeight', 'kRailReserve'):
        swift += f'    static let {key[1].lower() + key[2:]}: CGFloat = {constants[key]}\n'
    swift += '    static let examples: [ExampleRow] = [\n'
    for title, detail, category, icon, activity in titles:
        swift += f'        ExampleRow(title: {swift_string(title)}, detail: {swift_string(detail)}, category: {swift_string(category)}, destination: .{dict(Go='go', Switch='switchTab', Action='action')[icon]}, activity: .{activity[0].lower()+activity[1:]}),\n'
    swift += '    ]\n}\n'
    write_changed(LAB / 'Sources/ArciumCommandBarStudio/ProductionContract.swift', swift.encode())
    manifest = {'owners': owners, 'files': {p: hashlib.sha256(data).hexdigest() for p, data in outputs.items()},
                'panel_sha256': hashlib.sha256(panel.encode()).hexdigest(), 'examples_sha256': hashlib.sha256(examples.encode()).hexdigest()}
    write_changed(manifest_path, (json.dumps(manifest, indent=2) + '\n').encode())
    return manifest


if __name__ == '__main__':
    try:
        manifest = materialize()
        print(f'Production settings: {len(manifest["files"])} files from {len(manifest["owners"])} patches; no Chromium checkout')
    except (ValueError, KeyError, FileNotFoundError) as error:
        print(f'prepare: {error}', file=sys.stderr)
        sys.exit(1)
