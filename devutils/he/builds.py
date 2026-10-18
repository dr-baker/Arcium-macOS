"""Keep daily and diagnostic compilation separate, and verify completed apps."""

from __future__ import annotations

from pathlib import Path
import re

from . import apps
from .common import HeError, Paths, read_json, sha256_file, write_json

RECEIPT = "arcium-build.json"
MODES = ("daily", "diagnostics")
_BOOL = re.compile(r"^\s*(\w+)\s*=\s*(true|false)\s*(?:#.*)?$")
_ASSIGN = re.compile(r"^\s*(\w+)\s*=")


def configuration_problems(out: Path, mode: str) -> list[str]:
    """The few compile-time settings that define a mode must be explicit."""
    try:
        lines = (out / "args.gn").read_text().splitlines()
    except FileNotFoundError:
        return [f"no {mode} configuration in {out}; run he configure --{mode} --refresh-defaults"]
    values = {}
    for line in lines:
        if match := _BOOL.fullmatch(line):
            values[match[1]] = match[2] == "true"
        elif match := _ASSIGN.match(line):
            values[match[1]] = None
    expected = {"dcheck_always_on": mode == "diagnostics",
                "enable_expensive_dchecks": mode == "diagnostics"}
    if mode == "daily":
        expected["is_debug"] = False
    return [f"{mode} output requires {key}={str(value).lower()}; "
            f"run he configure --{mode} --refresh-defaults"
            for key, value in expected.items() if values.get(key) is not value]


def record_completed(paths: Paths, targets: list[str]) -> dict | None:
    """Called only after a successful real build of the chrome target."""
    if "chrome" not in targets or any(target.startswith("-") for target in targets):
        return None
    if problems := configuration_problems(paths.out, paths.build_mode):
        raise HeError("\n".join(problems))
    # Some small test graphs name their object aggregate 'chrome'. They do
    # not produce an installable app, and therefore get no receipt.
    app = paths.out / "Helium.app"
    if not app.is_dir() or not apps.executable(app).is_file():
        return None
    receipt = {"version": 1, "build_mode": paths.build_mode,
               "output": paths.out.name, "args_hash": sha256_file(paths.out / "args.gn"),
               "build_fingerprint": apps.build_fingerprint(paths.out)}
    write_json(paths.out / RECEIPT, receipt)
    return receipt


def require_completed(out: Path, mode: str) -> dict:
    """Reconfiguring args.gn never certifies an existing binary."""
    if mode not in MODES:
        raise HeError(f"unknown build mode: {mode}")
    expected_out = "Default" if mode == "daily" else "Diagnostics"
    if out.name != expected_out:
        raise HeError(f"{mode} apps must come from out/{expected_out}, not {out}")
    if problems := configuration_problems(out, mode):
        raise HeError("\n".join(problems))
    try:
        receipt = read_json(out / RECEIPT)
    except (OSError, ValueError):
        receipt = None
    if (not isinstance(receipt, dict) or receipt.get("version") != 1
            or receipt.get("build_mode") != mode or receipt.get("output") != out.name
            or receipt.get("args_hash") != sha256_file(out / "args.gn")
            or receipt.get("build_fingerprint") != apps.build_fingerprint(out)):
        raise HeError(f"no verified completed {mode} build in {out}; "
                      f"run he build --{mode} chrome before launching or installing")
    return receipt
