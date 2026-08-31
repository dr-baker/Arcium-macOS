#!/usr/bin/env python3
"""Inspect one selected Arcium build lane without changing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from build_lane import LaneError, LaneSpec, inspect_lane


GIB = 1024**3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", choices=("local", "heavy", "worktree"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--minimum-free-gib", type=int, default=15)
    parser.add_argument("--expected-volume-uuid")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.minimum_free_gib < 0:
        print("minimum free space must not be negative", file=sys.stderr)
        return 2
    heavy = arguments.name == "heavy"
    spec = LaneSpec(
        name=arguments.name,
        root=arguments.root,
        minimum_free_bytes=arguments.minimum_free_gib * GIB,
        expected_volume_uuid=arguments.expected_volume_uuid or None,
        require_external=heavy,
        require_case_sensitive_apfs=heavy,
        warn_if_unencrypted=heavy,
        warn_if_ownership_disabled=heavy,
    )
    try:
        report = inspect_lane(spec)
    except LaneError as error:
        print(str(error), file=sys.stderr)
        return 2
    document = {
        "ok": report.ok,
        "lane": report.spec.name,
        "root": str(report.spec.root.expanduser().resolve(strict=False)),
        "mount_point": str(report.volume.mount_point),
        "volume_uuid": report.volume.volume_uuid,
        "free_bytes": report.volume.free_bytes,
        "filesystem": report.volume.filesystem_name,
        "external": report.volume.external,
        "solid_state": report.volume.solid_state,
        "diagnostics": [
            {
                "severity": item.severity,
                "code": item.code,
                "message": item.message,
            }
            for item in report.diagnostics
        ],
    }
    if arguments.json:
        json.dump(document, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    else:
        gib = report.volume.free_bytes / GIB
        print(
            f"lane {report.spec.name}: {document['root']} "
            f"({gib:.1f} GiB free on {report.volume.filesystem_name or 'unknown filesystem'})"
        )
        for item in report.diagnostics:
            stream = sys.stderr if item.severity == "error" else sys.stdout
            print(f"{item.severity}: {item.message}", file=stream)
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
