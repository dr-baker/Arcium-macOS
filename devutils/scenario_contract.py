#!/usr/bin/env python3
"""Validate deterministic development-test scenario descriptions."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Mapping


_SCENARIO_ID = re.compile(r"[a-z][a-z0-9-]{0,63}")
_FEATURE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_TARGET = re.compile(r"//[A-Za-z0-9_./+-]+:[A-Za-z0-9_.+-]+")


class ScenarioError(ValueError):
    """A scenario cannot be executed deterministically."""


@dataclass(frozen=True)
class ScenarioTest:
    target: str
    filters: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioContract:
    scenario_id: str
    description: str
    profile_policy: str
    profile_name: str
    feature_flags: tuple[str, ...]
    tests: tuple[ScenarioTest, ...]
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    observables: tuple[str, ...]
    verify_persistence: bool
    verify_teardown: bool


def _string_list(payload: Mapping[str, object], key: str, *, required: bool = False) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ScenarioError(f"{key} must be a list of nonempty strings")
    result = tuple(item.strip() for item in value)
    if required and not result:
        raise ScenarioError(f"{key} must not be empty")
    return result


def parse_scenario(payload: Mapping[str, object]) -> ScenarioContract:
    """Parse one scenario while rejecting ambiguous profiles and target labels."""
    allowed = {
        "schema",
        "id",
        "description",
        "profile",
        "feature_flags",
        "tests",
        "preconditions",
        "steps",
        "observables",
        "verify_persistence",
        "verify_teardown",
    }
    unknown = set(payload).difference(allowed)
    if unknown:
        raise ScenarioError(f"unknown scenario fields: {', '.join(sorted(unknown))}")
    if payload.get("schema") != 1:
        raise ScenarioError("scenario schema must be 1")
    scenario_id = payload.get("id")
    if not isinstance(scenario_id, str) or not _SCENARIO_ID.fullmatch(scenario_id):
        raise ScenarioError("id must be a stable lowercase scenario identifier")
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ScenarioError("description must be a nonempty string")
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        raise ScenarioError("profile must be an object")
    if set(profile).difference({"policy", "name"}):
        raise ScenarioError("profile contains unknown fields")
    policy = profile.get("policy")
    if policy not in {"persistent-dev", "isolated", "fresh"}:
        raise ScenarioError("profile policy must be persistent-dev, isolated, or fresh")
    profile_name = profile.get("name")
    if policy == "persistent-dev":
        if profile_name not in {None, ""}:
            raise ScenarioError("persistent-dev profile must not have a name")
        profile_name = ""
    elif not isinstance(profile_name, str) or not _SCENARIO_ID.fullmatch(profile_name):
        raise ScenarioError("isolated and fresh profiles require a safe name")
    feature_flags = _string_list(payload, "feature_flags")
    invalid_flags = [flag for flag in feature_flags if not _FEATURE_NAME.fullmatch(flag)]
    if invalid_flags:
        raise ScenarioError(f"invalid feature flags: {', '.join(invalid_flags)}")
    raw_tests = payload.get("tests", [])
    if not isinstance(raw_tests, list):
        raise ScenarioError("tests must be a list")
    tests: list[ScenarioTest] = []
    for index, raw_test in enumerate(raw_tests):
        if not isinstance(raw_test, dict) or set(raw_test).difference({"target", "filters"}):
            raise ScenarioError(f"tests[{index}] must contain only target and filters")
        target = raw_test.get("target")
        if not isinstance(target, str) or not _TARGET.fullmatch(target):
            raise ScenarioError(f"tests[{index}].target is not an explicit GN label")
        filters = _string_list(raw_test, "filters")
        tests.append(ScenarioTest(target=target, filters=filters))
    verify_persistence = payload.get("verify_persistence", False)
    verify_teardown = payload.get("verify_teardown", False)
    if not isinstance(verify_persistence, bool) or not isinstance(verify_teardown, bool):
        raise ScenarioError("verification fields must be boolean")
    return ScenarioContract(
        scenario_id=scenario_id,
        description=description.strip(),
        profile_policy=str(policy),
        profile_name=str(profile_name),
        feature_flags=feature_flags,
        tests=tuple(tests),
        preconditions=_string_list(payload, "preconditions", required=True),
        steps=_string_list(payload, "steps", required=True),
        observables=_string_list(payload, "observables", required=True),
        verify_persistence=verify_persistence,
        verify_teardown=verify_teardown,
    )


def load_scenario(path: Path) -> ScenarioContract:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScenarioError(f"could not read scenario: {path}") from error
    if not isinstance(payload, dict):
        raise ScenarioError("scenario root must be an object")
    return parse_scenario(payload)
