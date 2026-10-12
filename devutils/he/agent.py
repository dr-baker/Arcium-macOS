"""Checks behind the `he agent` prefix, and the state behind `he check --json`.

`he agent CMD` runs any he command. Two get stricter: `build` refuses a
broad dry-run plan without --approved, refuses while a timestamp snapshot is
pending, and refuses when `he check` reports problems; `arcium` refuses to
restart a running Arcium without --approved (see arcium.install). A human
never meets these checks without typing `he agent`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time

from . import apps, quilt, timestamps
from .common import HeError, Paths, write_json

DEFAULT_EDGE_BUDGET = 500
_PROGRESS = re.compile(r"\[\s*\d+\s*/\s*(\d+)\s*\]")


_SISO_NOISE = re.compile(r"^(?:[\d.ms]+\s+)?(?:schedule pending|build start|rebuild manifest|loading build|"
                         r"load siso|ninja explain|disable fast local| use `)|^\s*$")


def planned_edges(output: str) -> int:
    """Edges a dry run would run.

    Ninja prints "[done/total]" progress. Siso prints each planned command on
    its own line between "rebuild manifest finished" and "build finished".
    """
    totals = [int(total) for total in _PROGRESS.findall(output)]
    if totals:
        return max(totals)
    lines = output.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("rebuild manifest finished")]
    if not starts:
        return 0
    body = []
    for line in lines[starts[-1] + 1:]:
        if line.startswith("build finished"):
            break
        body.append(line)
    return sum(1 for line in body if not _SISO_NOISE.match(line))


def guard_build(paths: Paths, targets: list[str], *, budget: int, approved: bool, problems: list[str]) -> int:
    """Refuse a build an agent should not start; return the planned edge count."""
    if not targets:
        raise HeError("he agent build needs explicit targets, for example: he agent build chrome")
    if timestamps.pending(paths):
        raise HeError("a timestamp snapshot is pending; run he agent push to finish the stack before building")
    if problems:
        raise HeError("he check reports problems; fix them first:\n  " + "\n  ".join(problems))
    out = paths.src / "out" / "Default"
    command = ["python3", str(paths.src / "third_party" / "depot_tools" / "autoninja.py"), "-C", str(out), "-n", *targets]
    environment = {**os.environ, "SISO_PATH": str(paths.src / "third_party" / "siso" / "cipd" / "siso")}
    import sys
    print(f"he agent build: dry run of {' '.join(targets)} to check the edge budget "
          "(loading the build graph takes 30-60 s)", file=sys.stderr, flush=True)
    result = subprocess.run(command, cwd=paths.src, env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        raise HeError(f"dry run failed:\n{(result.stdout + result.stderr).strip()[-2000:]}")
    output = result.stdout + result.stderr
    edges = planned_edges(output)
    print(f"he agent build: {edges} edges planned (budget {budget})", file=sys.stderr, flush=True)
    if edges > budget and not approved:
        plan = paths.state / "last-plan.txt"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(output, errors="replace")
        commands = [line for line in output.splitlines() if line.strip() and not _SISO_NOISE.match(line)
                    and not line.startswith(("depot_tools/", "ninja:", "offline mode", "build finished", "local:", "fs:"))]
        sample = "\n  ".join(line[:160] for line in commands[:8])
        raise HeError(f"this build plans {edges} edges, above the budget of {budget}.\n"
                      f"First planned commands:\n  {sample}\n"
                      f"Full dry run: {plan}. Siso records why each step is dirty in {out / 'siso_explain'}.\n"
                      "Fix the cause, or rerun with --approved if the breadth is expected.")
    return edges


def status(paths: Paths, problems: list[str]) -> dict:
    series = quilt.read_list(paths.catalog / "series.merged")
    applied = quilt.applied(paths.src)
    scratch_root = paths.state / "scratch"
    profiles = Path.home() / "Library" / "Application Support" / "Helium Development" / "profiles"
    running = []
    for profile in sorted(profiles.glob("*/*")) + [Path.home() / "Library" / "Application Support" / "net.imput.helium.dev"]:
        pid = apps.profile_owner(profile)
        # A stale lock can name a pid now reused by an unrelated process.
        if pid is not None and "/Helium Dev" in (path := apps.process_path(pid) or "") and apps.uses_profile(pid, profile):
            running.append({"profile": str(profile), "pid": pid, "executable": path})
    return {
        "worktree": str(paths.worktree),
        "build_dir": str(paths.build_dir),
        "scratch": (paths.state / "scratch.json").is_file(),
        "patches": {"series": len(series), "applied": len(applied), "top": applied[-1] if applied else None},
        "timestamp_snapshot_pending": timestamps.pending(paths),
        "problems": problems,
        "scratches": sorted(p.name for p in scratch_root.iterdir()) if scratch_root.is_dir() else [],
        "running_dev_profiles": running,
    }


def dumps(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True)
