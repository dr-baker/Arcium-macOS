#!/usr/bin/env python3
"""Run tab invariant suites, rejecting missing, skipped, or unreported tests.

Use --build to compile and execute under one lane lock. Without --build,
results record binary identity but do not certify source freshness.
"""
from __future__ import annotations

import argparse
import fcntl
from dataclasses import dataclass
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class Suite:
    binary: str
    filters: tuple[str, ...]
    required: tuple[str, ...]


SUITES = {
    "model": Suite(
        "helium_persistent_item_model_tests",
        ("*",),
        ("FixedSeeds/PersistentItemInvariantTest.LifecycleOwnershipAcrossActionSequences/0",
         "FixedSeeds/PersistentItemInvariantTest.TreeMovesPreserveIdentityAndPersistence/0")),
    "service": Suite(
        "arcium_feature_settings_unit_tests", ("HeliumSpaceServiceTest.*",),
        ("HeliumSpaceServiceTest.ActionSequencesPreserveTabOwnership",)),
    "browser": Suite(
        "browser_tests", ("HeliumPersistentTabViewTest.*",),
        ("HeliumPersistentTabViewTest.ActionSequencesPreserveVisibleTabsAndPageState",
         "HeliumPersistentTabViewTest.ProjectedLivePinRemainsVisibleAfterUnpin",
         "HeliumPersistentTabViewTest.UnfavoriteRemovesRetiringFavoriteViews",
         "HeliumPersistentTabViewTest.PinMoveReportsPreviousSelectedIndex")),
}


class GateFailure(RuntimeError):
    pass


def run_command(command: list[str], *, timeout: int, **kwargs):
    """Stop the complete launcher/build process group if its deadline expires."""
    with subprocess.Popen(command, start_new_session=True, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def listed_tests(output: str) -> set[str]:
    result = set()
    suite = ""
    for line in output.splitlines():
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        if not line[0].isspace() and name.endswith("."):
            suite = name
        elif line[0].isspace() and suite and " " not in name:
            result.add(suite + name)
    return result


def verify_xml(path: Path, expected: set[str]) -> int:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise GateFailure(f"Missing or invalid test results: {path}") from error
    observed = []
    for case in root.iter("testcase"):
        name = case.get("classname", "") + "." + case.get("name", "")
        if (case.find("failure") is not None or case.find("error") is not None
                or case.find("skipped") is not None
                or case.get("status") == "notrun"
                or case.get("result") in {"skipped", "suppressed"}):
            raise GateFailure(f"Failed or skipped test: {name}")
        observed.append(name)
    if not expected or set(observed) != expected or len(observed) != len(expected):
        raise GateFailure(
            f"Test inventory mismatch: missing={sorted(expected - set(observed))}, "
            f"unexpected={sorted(set(observed) - expected)}, count={len(observed)}")
    return len(observed)


def verify_launcher_json(path: Path, expected: set[str]) -> int:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise GateFailure(f"Missing or invalid launcher results: {path}") from error
    iterations = payload.get("per_iteration_data") if isinstance(payload, dict) else None
    if not isinstance(iterations, list) or len(iterations) != 1:
        raise GateFailure("Expected exactly one completed test iteration")
    results = iterations[0]
    if not isinstance(results, dict) or not expected or set(results) != expected:
        raise GateFailure("Launcher results do not match the discovered test inventory")
    for name, attempts in results.items():
        if (not isinstance(attempts, list) or len(attempts) != 1
                or not isinstance(attempts[0], dict)
                or attempts[0].get("status") != "SUCCESS"):
            raise GateFailure(f"Failed, skipped or retried test: {name}")
    return len(results)


def run_suite(suite: Suite, out: Path, report: Path, timeout: int) -> dict:
    binary = (out / suite.binary).resolve()
    if not binary.is_file():
        raise GateFailure(f"Build the missing target first: {binary}")
    common = [str(binary), "--gtest_filter=" + ":".join(suite.filters)]
    listing = run_command(common + ["--gtest_list_tests"], cwd=out,
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout)
    (report / "inventory.log").write_text(listing.stdout + listing.stderr)
    if listing.returncode:
        raise GateFailure(f"Test discovery exited {listing.returncode}")
    expected = listed_tests(listing.stdout)
    missing = set(suite.required) - expected
    if not expected or missing:
        raise GateFailure(f"Binary lacks required tests: {sorted(missing)}")
    # A fresh directory ensures a crash cannot reuse an earlier passing XML.
    uses_launcher = suite.binary in {
        "unit_tests", "browser_tests", "arcium_feature_settings_unit_tests"}
    results = report / ("launcher-summary.json" if uses_launcher else "results.xml")
    output_flag = (f"--test-launcher-summary-output={results}" if uses_launcher
                   else f"--gtest_output=xml:{results}")
    command = common + [output_flag, "--test-launcher-jobs=1",
                        "--test-launcher-retry-limit=0", "--use-mock-keychain"]
    with (report / "run.log").open("w") as log:
        result = run_command(command, cwd=out, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise GateFailure(f"Tests exited {result.returncode}; see {report / 'run.log'}")
    count = (verify_launcher_json(results, expected) if uses_launcher
             else verify_xml(results, expected))
    with binary.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"binary": str(binary), "sha256": digest,
            "passed": count, "command": command}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=[*SUITES, "all"], default="all")
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--build", action="store_true",
                        help="Compile each target under the same lane lock before running")
    parser.add_argument("--driver-checkout", type=Path,
                        help="Canonical checkout containing dev.sh, required with --build")
    args = parser.parse_args()
    if args.build and (not args.driver_checkout or
                       not (args.driver_checkout / "dev.sh").is_file()):
        parser.error("--build requires --driver-checkout with dev.sh")
    tiers = SUITES if args.tier == "all" else [args.tier]
    args.report_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="tab-invariants-", dir=args.report_dir))
    summary = {"status": "failed", "tiers": {}, "source_freshness": "not-certified"}
    try:
        if args.build:
            # he build takes the build-dir lock itself.
            environment = dict(os.environ, HELIUM_BUILD_DIR=str(args.build_root.resolve()),
                               HELIUM_DEV_WORKTREE=str(Path(__file__).resolve().parents[1]))
            with (run_dir / "build.log").open("w") as log:
                build = run_command([
                    "bash", "-c", 'source "$1/dev.sh" >/dev/null && shift && he build "$@"',
                    "tab-invariants", str(args.driver_checkout.resolve()),
                    *(SUITES[tier].binary for tier in tiers)], env=environment,
                    stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
            if build.returncode:
                raise GateFailure(f"Build failed; see {run_dir / 'build.log'}")
        # Hold the build-dir lock while tests run, so no he command changes
        # the binaries or source underneath them.
        with (args.build_root / ".arcium" / "lane.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise GateFailure("the build dir is busy with another he command") from None
            for tier in tiers:
                report = run_dir / tier
                report.mkdir()
                summary["tiers"][tier] = run_suite(
                    SUITES[tier], args.build_root / "src/out/Default", report,
                    args.timeout)
        summary["status"] = "passed"
        if args.build:
            summary["source_freshness"] = "built-before-locked-run"
    except (GateFailure, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        summary["error"] = str(error)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"report": str(run_dir), **summary}, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
