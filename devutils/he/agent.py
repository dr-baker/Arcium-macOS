"""The agent path, `he agent ...`: the same commands with stricter checks.

A human never meets these checks unless they type `he agent`. Agents get:
- a dry-run edge budget on builds, overridden only with --approved;
- refusal to build while a timestamp snapshot is pending;
- `he check` problems as errors instead of warnings;
- one JSON result per command in .arcium/agent/last-<command>.json.
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
    result = subprocess.run(command, cwd=paths.src, env=environment, capture_output=True, text=True, check=False)
    if result.returncode:
        raise HeError(f"dry run failed:\n{(result.stdout + result.stderr).strip()[-2000:]}")
    edges = planned_edges(result.stdout + result.stderr)
    if edges > budget and not approved:
        raise HeError(f"this build plans {edges} edges, above the budget of {budget}; "
                      "rerun with --approved if the work justifies it, or raise --edge-budget")
    return edges


def record_result(paths: Paths, command: str, status: int, seconds: float, log: Path | None, extra: dict) -> dict:
    lines = log.read_text(errors="replace").splitlines() if log and log.is_file() else []
    errors = [line for line in lines if re.search(r"\b(error|failed|FAILED)\b", line)][:20]
    result = {"command": command, "outcome": "ok" if status == 0 else "failed", "exit_status": status,
              "seconds": round(seconds, 1), "first_errors": errors, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "build_dir": str(paths.build_dir), "worktree": str(paths.worktree), **extra}
    write_json(paths.state / "agent" / f"last-{command}.json", result)
    return result


def run_and_record(paths: Paths, name: str, argv: list[str], *, as_json: bool) -> int:
    """Run one agent action, echo its output, and record a JSON result."""
    import sys
    import tempfile
    import threading

    started = time.monotonic()
    with tempfile.NamedTemporaryFile("w+b", prefix="he-agent-", delete=False) as log:
        log_path = Path(log.name)
    lock = threading.Lock()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def copy(stream, sink):
        for chunk in iter(lambda: stream.readline(), b""):
            sink.write(chunk)
            sink.flush()
            with lock, log_path.open("ab") as handle:
                handle.write(chunk)

    threads = [threading.Thread(target=copy, args=(process.stdout, sys.stdout.buffer)),
               threading.Thread(target=copy, args=(process.stderr, sys.stderr.buffer))]
    for thread in threads:
        thread.start()
    status = process.wait()
    for thread in threads:
        thread.join()
    result = record_result(paths, name, status, time.monotonic() - started, log_path, {})
    log_path.unlink(missing_ok=True)
    if as_json:
        print(dumps(result))
    return status


def status(paths: Paths, problems: list[str]) -> dict:
    series = quilt.read_list(paths.catalog / "series.merged")
    applied = quilt.applied(paths.src)
    scratch_root = paths.state / "scratch"
    profiles = Path.home() / "Library" / "Application Support" / "Helium Development" / "profiles"
    running = []
    for profile in sorted(profiles.glob("*/*")) + [Path.home() / "Library" / "Application Support" / "net.imput.helium.dev"]:
        if (pid := apps.profile_owner(profile)) is not None:
            running.append({"profile": str(profile), "pid": pid, "executable": apps.process_path(pid)})
    return {
        "worktree": str(paths.worktree),
        "build_dir": str(paths.build_dir),
        "scratch": (paths.state / "scratch.json").is_file(),
        "patches": {"series": len(series), "applied": len(applied), "top": applied[-1] if applied else None},
        "timestamp_snapshot_pending": timestamps.pending(paths),
        "problems": problems,
        "scratches": sorted(p.name for p in scratch_root.iterdir()) if scratch_root.is_dir() else [],
        "running_dev_profiles": running,
        "last_results": sorted(p.name for p in (paths.state / "agent").glob("last-*.json")),
    }


def dumps(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True)
