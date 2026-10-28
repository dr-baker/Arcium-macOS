#!/usr/bin/env python3
"""List personal patch-owned production objects from the configured build graph."""

import argparse
import json
from pathlib import Path
import re
import shlex
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_TEST = re.compile(
    r"(?:^|/)(?:test|tests|testing|test_support|test_utils)/"
    r"|(?:^|/)test_[^/]*\.(?:cc|mm)$"
    r"|(?:_|/)(?:unittest|browsertest|uitest|apitest|pixeltest|"
    r"browser_test|unit_test|test_support|test_utils|test_util|"
    r"test_environment|test_base|interactive_uitest|fuzzer)(?:[_.]|$)"
)


def personal_sources(root):
    sources = set()
    for patches in (root / 'helium-chromium/patches', root / 'patches'):
        for line in (patches / 'series').read_text().splitlines():
            fields = shlex.split(line, comments=True)
            if not fields or not fields[0].startswith('personal/'):
                continue
            patch = (patches / fields[0]).resolve()
            if not patch.is_relative_to(patches.resolve()):
                raise ValueError(f'Patch escapes its catalog: {fields[0]}')
            previous = ''
            for line in patch.read_text().splitlines():
                if previous.startswith('--- ') and line.startswith('+++ '):
                    name = shlex.split(line[4:].split('\t', 1)[0])[0]
                    if name.startswith(('src/', 'b/')):
                        name = name.split('/', 1)[1]
                    path = Path(name)
                    if path.suffix in ('.cc', '.mm') and not SOURCE_TEST.search(name):
                        if path.is_absolute() or '..' in path.parts:
                            raise ValueError(f'Invalid source path: {name}')
                        sources.add(name)
                previous = line
    return sources


def is_test_output(output):
    return (re.search(r'(?:^|/)(?:test|tests|testing)(?:/|$)', output)
            or re.search(r'(?:^|_)(?:tests?|unittests?|browsertests?|uitests?|'
                         r'fuzzer|test_support)(?:_|$)', Path(output).parent.name)
            or '/test_support' in output)


def inventory(root, build_dir, daily=False):
    src = (build_dir / 'src').resolve()
    out = src / 'out' / ('Default' if daily else 'Diagnostics')
    sources = personal_sources(root)
    missing = sorted(name for name in sources if not (src / name).is_file())
    sources.difference_update(missing)
    targets, matched = set(), set()
    for entry in json.loads((out / 'compile_commands.json').read_text()):
        directory = Path(entry['directory'])
        filename = (directory / entry['file']).resolve()
        if not filename.is_relative_to(src):
            continue
        name = filename.relative_to(src).as_posix()
        if name not in sources:
            continue
        args = entry.get('arguments') or shlex.split(entry.get('command', ''))
        output = entry.get('output') or args[args.index('-o') + 1]
        object_path = (directory / output).resolve()
        if not object_path.is_relative_to(out) or object_path.suffix != '.o':
            raise ValueError(f'Object is outside the selected output: {output}')
        target = object_path.relative_to(out).as_posix()
        if not is_test_output(target):
            targets.add(target)
            matched.add(name)
    return dict(targets=sorted(targets), matched_sources=len(matched),
                unmatched_sources=sorted(sources - matched), missing_sources=missing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--daily', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        result = inventory(args.root.resolve(), args.build_dir.resolve(), args.daily)
    except (OSError, ValueError, IndexError, KeyError) as error:
        parser.exit(1, f'Cannot inspect build targets: {error}\n')
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print('\n'.join(result['targets']))
        print(f"{len(result['targets'])} objects; "
              f"{len(result['unmatched_sources'])} sources outside this graph; "
              f"{len(result['missing_sources'])} absent sources. Use --json for paths.",
              file=sys.stderr)


if __name__ == '__main__':
    main()
