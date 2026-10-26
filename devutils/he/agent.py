"""Checks behind the `he agent` prefix, and the state behind `he check --json`.

`he agent CMD` runs any he command. Two get stricter: `build` refuses a
broad dry-run plan without --approved, refuses while a timestamp snapshot is
pending, and refuses when `he check` reports problems; `arcium` refuses to
restart a running Arcium without --approved (see arcium.install). A human
never meets these checks without typing `he agent`.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
import itertools
import os
from pathlib import Path
import re
import subprocess
import shutil
import time

from . import apps, quilt, timestamps
from .common import HeError, Paths, write_json

DEFAULT_EDGE_BUDGET = 500
_PROGRESS = re.compile(r"\[\s*\d+\s*/\s*(\d+)\s*\]")


_SISO_NOISE = re.compile(r"^(?:[\d.ms]+\s+)?(?:schedule pending|build start|rebuild manifest|loading build|"
                         r"load siso|ninja explain|disable fast local| use `)|^\s*$")


def planned_edges(output) -> int | None:
    """Edges a dry run would run.

    Ninja prints "[done/total]" progress. Siso prints each planned command on
    its own line between "rebuild manifest finished" and "build finished".
    """
    total = done = None
    count = None
    finished = no_work = False
    for line in output.splitlines() if isinstance(output,str) else output:
        no_work |= bool(re.match(r"^\s*(?:ninja: no work to do\.?|no work to do\.)\s*$",line,re.I))
        if line.startswith(("rebuild manifest finished","build start:")):
            count, finished = 0, False
            total = done = None
        elif line.startswith('build finished'):
            finished = count is not None
        elif count is not None and not finished and not _SISO_NOISE.match(line):
            count += 1
        elif count is None:
            if (match := re.match(r"^\[\s*(\d+)\s*/\s*(\d+)\s*\]",line)):
                done = max(done or 0,int(match[1]))
                total = max(total or 0,int(match[2]))
    if count is not None:
        return count if finished else None
    if total is not None:
        return total if done == total else None
    return 0 if no_work else None


def read_plan(paths, result):
    """Count a complete disk-spooled plan without loading it into memory."""
    output = (result.stdout or '') + (result.stderr or '')
    plan = paths.state/'last-plan.txt'
    plan.parent.mkdir(parents=True,exist_ok=True)
    files = [getattr(result,name+'_path',None) for name in ('stdout','stderr')]
    if all(files):
        with ExitStack() as stack:
            streams = [stack.enter_context(path.open(errors='replace')) for path in files]
            edges = planned_edges(itertools.chain.from_iterable(streams))
        with plan.open('wb') as destination:
            for path in files:
                with path.open('rb') as source:
                    shutil.copyfileobj(source,destination,1024*1024)
    else:
        edges = planned_edges(output)
        plan.write_text(output,errors='replace')
    return edges, output


_UNCOUNTED = object()


def guard_build(paths: Paths, targets: list[str], *, budget: int, approved: bool, problems: list[str],
                jobs: int | None = None, remote_jobs: int | None = None,
                output: str | None = None, edge_count=_UNCOUNTED, plan_saved=False) -> int:
    """Refuse a build an agent should not start; return the planned edge count."""
    if not targets:
        raise HeError("he agent build needs explicit targets, for example: he agent build chrome")
    if timestamps.pending(paths):
        raise HeError("a timestamp snapshot is pending; run he agent push to finish the stack before building")
    if problems:
        raise HeError("he check reports problems; fix them first:\n  " + "\n  ".join(problems))
    from . import resources
    command = resources.build_command(paths, targets, planning=True, offline=True)
    environment = {**os.environ, "SISO_PATH": str(paths.src / "third_party" / "siso" / "cipd" / "siso")}
    import sys
    from . import evidence
    evidence.message(f"he agent build: dry run of {' '.join(targets)} to check the edge budget "
                     "(loading the build graph takes 30-60 s)")
    # The dry run can run GN and load a large graph. Give it the same resource
    # admission and OS policy as compilation, while preserving its diagnostics.
    if output is None:
        result = resources.run(paths, command, jobs=resources.jobs_ceiling(jobs), capture_output=True, phase="plan",
                               environment=environment)
        if result.returncode:
            raise HeError(f"dry run failed:\n{(result.stdout + result.stderr).strip()[-2000:]}")
        edge_count, output = read_plan(paths,result)
        plan_saved = True
    edges = planned_edges(output) if edge_count is _UNCOUNTED else edge_count
    if edges is None:
        write_json(paths.state / "last-plan-error.json", {"reason": "unknown plan format"})
        if not plan_saved:
            (paths.state / "last-plan.txt").write_text(output, errors="replace")
        raise HeError("cannot count this dry-run plan; inspect .arcium/last-plan.txt before building")
    evidence.message(f"he agent build: {edges} edges planned (budget {budget})")
    if edges > budget and not approved:
        plan = paths.state / "last-plan.txt"
        plan.parent.mkdir(parents=True, exist_ok=True)
        if not plan_saved:
            plan.write_text(output, errors="replace")
        commands = [line for line in output.splitlines() if line.strip() and not _SISO_NOISE.match(line)
                    and not line.startswith(("depot_tools/", "ninja:", "offline mode", "build finished", "local:", "fs:"))]
        sample = "\n  ".join(line[:160] for line in commands[:8])
        raise HeError(f"this build plans {edges} edges, above the budget of {budget}.\n"
                      f"First planned commands:\n  {sample}\n"
                      f"Full dry run: {plan}. Siso records why each step is dirty in {paths.out / 'siso_explain'}.\n"
                      "Fix the cause, or rerun with --approved if the breadth is expected.")
    return edges


def status(paths: Paths, problems: list[str]) -> dict:
    from .lane import Lane
    from . import resources
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
        "build_mode": paths.build_mode,
        "lane": Lane(paths.state).status(),
        "build_resources": resources.status(paths.state),
        "output_dir": str(paths.out),
        "scratch": (paths.state / "scratch.json").is_file(),
        "patches": {"series": len(series), "applied": len(applied), "top": applied[-1] if applied else None},
        "timestamp_snapshot_pending": timestamps.pending(paths),
        "problems": problems,
        "scratches": sorted(p.name for p in scratch_root.iterdir()) if scratch_root.is_dir() else [],
        "running_dev_profiles": running,
    }


def dumps(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True)
