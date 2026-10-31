#!/usr/bin/env python3
"""Write review candidates from old/new Quilt preimages without editing source."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helium-chromium/devutils"))
from third_party.unidiff import PatchSet


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Expected a relative Quilt path: {value}")
    return path


def candidates(old_src, new_src, patch_name, patch_file, files, output):
    """Reconstruct the old postimage strictly, then merge it with the new base."""
    patch_name = relative_path(patch_name)
    files = [relative_path(file) for file in files]
    old_src, new_src, output = (path.resolve() for path in (old_src, new_src, output))
    if any(output == src or src in output.parents for src in (old_src, new_src)):
        raise ValueError("Candidate output must be outside both source trees")
    entries = {}
    for entry in PatchSet.from_filename(patch_file):
        if entry.target_file != "/dev/null":
            path = relative_path(entry.target_file.split("/", 1)[1])
            entries[path] = entry
    output.mkdir(parents=True, exist_ok=False)
    report = []
    for file in files:
        item = {"file": str(file)}
        report.append(item)
        old = old_src / ".pc" / patch_name / file
        new = new_src / ".pc" / patch_name / file
        if file not in entries or not old.is_file() or not new.is_file():
            item["error"] = "Missing patch entry or recorded preimage"
            continue
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            post = root / file
            post.parent.mkdir(parents=True, exist_ok=True)
            if entries[file].source_file == "/dev/null":
                if old.read_bytes():
                    item["error"] = "Added-file patch has a nonempty old preimage"
                    continue
            else:
                post.write_bytes(old.read_bytes())
            applied = subprocess.run(
                ["patch", "--batch", "--forward", "--fuzz=0", "-p1"], cwd=root,
                input=str(entries[file]), text=True, capture_output=True,
            )
            if applied.returncode:
                item["error"] = "Patch does not apply strictly to the old preimage"
                item["details"] = applied.stdout + applied.stderr
                continue
            # Keep merge inputs outside the reconstructed patch paths.
            with tempfile.TemporaryDirectory() as inputs:
                before = Path(inputs) / "before"
                incoming = Path(inputs) / "incoming"
                before.write_bytes(old.read_bytes())
                incoming.write_bytes(new.read_bytes())
                merged = subprocess.run(
                    ["git", "merge-file", "-p", "--diff3",
                     "-L", "new preimage", "-L", "old preimage", "-L", "local patch",
                     str(incoming), str(before), str(post)], capture_output=True,
                )
            if merged.returncode < 0 or merged.returncode > 127:
                item["error"] = merged.stderr.decode(errors="replace")
                continue
            destination = output / file
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(merged.stdout)
            item["conflicts"] = sum(line.startswith(b"<<<<<<< ") for line in merged.stdout.splitlines())
            item["candidate"] = str(destination)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-src", type=Path, required=True)
    parser.add_argument("--new-src", type=Path, required=True)
    parser.add_argument("--patch-name", required=True, help="Quilt series name, e.g. personal/arcium-spaces.patch")
    parser.add_argument("--patch", type=Path, required=True, help="Authoritative repository patch, before refreshing it")
    parser.add_argument("--file", action="append", required=True, help="Affected path relative to Chromium src; repeat as needed")
    parser.add_argument("--output", type=Path, required=True, help="New directory outside both source trees")
    args = parser.parse_args()
    try:
        result = candidates(args.old_src, args.new_src, args.patch_name,
                            args.patch, args.file, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot prepare candidates: {error}\n")
    for item in result:
        print(f'{item["file"]}: {item.get("error", str(item.get("conflicts", 0)) + " conflicts")}')
    print(f"Review {args.output / 'report.json'}; no source or repository patch was changed.")
    return int(any("error" in item for item in result))


if __name__ == "__main__":
    sys.exit(main())
