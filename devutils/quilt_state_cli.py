#!/usr/bin/env python3
"""Verify that one generated source tree matches its declared Quilt series."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from quilt_state import QuiltStateError, inspect_quilt_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--patches", type=Path, required=True)
    parser.add_argument("--series", default="series.merged")
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = inspect_quilt_state(
            arguments.source,
            arguments.patches,
            series_name=arguments.series,
        )
        if arguments.complete:
            report.comparison.require_complete()
        else:
            report.comparison.require_valid_prefix()
    except QuiltStateError as error:
        print(str(error), file=sys.stderr)
        return 2
    document = {
        "ok": True,
        "source_dir": str(report.source_dir),
        "patches_dir": str(report.patches_dir),
        "series": report.series_name,
        "declared_count": len(report.comparison.declared),
        "applied_count": len(report.comparison.applied),
        "complete": report.comparison.complete,
        "declared_sha256": report.declared_sha256,
        "applied_sha256": report.applied_sha256,
        "top": report.comparison.applied[-1] if report.comparison.applied else None,
    }
    if arguments.json:
        json.dump(document, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
    else:
        print(
            "Quilt: "
            f"{document['applied_count']}/{document['declared_count']} patches applied; "
            f"top {document['top'] or '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
