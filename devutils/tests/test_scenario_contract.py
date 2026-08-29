"""Tests for deterministic test-scenario contracts."""

import unittest

from devutils.scenario_contract import ScenarioError, parse_scenario


def valid_payload():
    return {
        "schema": 1,
        "id": "example-drag",
        "description": "Exercise a deterministic example drag.",
        "profile": {"policy": "isolated", "name": "example-drag"},
        "feature_flags": ["ExampleFeature"],
        "tests": [
            {
                "target": "//chrome/browser/ui:example_tests",
                "filters": ["ExampleTest.Drag"],
            }
        ],
        "preconditions": ["Seed two example rows"],
        "steps": ["Drag the first row after the second"],
        "observables": ["The order changes"],
        "verify_persistence": True,
        "verify_teardown": True,
    }


class ScenarioContractTest(unittest.TestCase):
    def test_valid_scenario_preserves_explicit_test_and_profile_policy(self) -> None:
        scenario = parse_scenario(valid_payload())
        self.assertEqual(scenario.scenario_id, "example-drag")
        self.assertEqual(scenario.profile_policy, "isolated")
        self.assertEqual(scenario.tests[0].target, "//chrome/browser/ui:example_tests")
        self.assertTrue(scenario.verify_persistence)

    def test_persistent_profile_rejects_a_caller_selected_name(self) -> None:
        payload = valid_payload()
        payload["profile"] = {"policy": "persistent-dev", "name": "unsafe-alias"}
        with self.assertRaisesRegex(ScenarioError, "must not have a name"):
            parse_scenario(payload)

    def test_disposable_profile_requires_a_safe_name(self) -> None:
        payload = valid_payload()
        payload["profile"] = {"policy": "fresh", "name": "../profile"}
        with self.assertRaisesRegex(ScenarioError, "safe name"):
            parse_scenario(payload)

    def test_test_target_must_be_an_explicit_gn_label(self) -> None:
        payload = valid_payload()
        payload["tests"][0]["target"] = "browser_tests"
        with self.assertRaisesRegex(ScenarioError, "explicit GN label"):
            parse_scenario(payload)

    def test_unknown_fields_and_invalid_feature_flags_are_rejected(self) -> None:
        payload = valid_payload()
        payload["mystery"] = True
        with self.assertRaisesRegex(ScenarioError, "unknown scenario fields"):
            parse_scenario(payload)
        payload = valid_payload()
        payload["feature_flags"] = ["Feature,OtherFeature"]
        with self.assertRaisesRegex(ScenarioError, "invalid feature flags"):
            parse_scenario(payload)

    def test_behavior_steps_and_observables_are_required(self) -> None:
        for key in ("preconditions", "steps", "observables"):
            payload = valid_payload()
            payload[key] = []
            with self.subTest(key=key):
                with self.assertRaisesRegex(ScenarioError, f"{key} must not be empty"):
                    parse_scenario(payload)


if __name__ == "__main__":
    unittest.main()
