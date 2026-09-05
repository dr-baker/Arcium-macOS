import unittest

from devutils.feature_performance import outcomes, summarize


class FeaturePerformanceTest(unittest.TestCase):
    def event(self, latency, *, glass=True, opening=True):
        return {"name": "Arcium.MRU.Presented", "args": {
            "latency_us": latency, "glass": glass, "opening": opening}}

    def test_modes_and_open_cycle_are_separate(self):
        report = summarize({"traceEvents": [
            self.event(1000), self.event(3000),
            self.event(7000, glass=False), self.event(5000, opening=False)]})
        self.assertEqual(report["glass.open"], {
            "count": 2, "median_ms": 2.0, "p95_ms": 3.0, "max_ms": 3.0})
        self.assertEqual(report["opaque.open"]["median_ms"], 7.0)
        self.assertEqual(report["glass.cycle"]["count"], 1)

    def test_invalid_and_unrelated_samples_are_excluded(self):
        self.assertEqual(summarize({"traceEvents": [
            self.event(-1), self.event(float("nan")), self.event(True),
            self.event(2, glass="false"), {"name": "Private page title"},
        ]}), {})

    def test_empty_trace_is_not_a_zero_latency_measurement(self):
        self.assertEqual(summarize({}), {})

    def test_outcomes_preserve_missing_latency_denominator_by_mode(self):
        events = [{"name": "Arcium.MRU.PresentationOutcome", "args": {
            "outcome": value, "glass": glass}}
            for value, glass in [(0, True), (1, True), (1, True),
                                 (2, False), (3, False), (4, True)]]
        report = outcomes({"traceEvents": events})
        self.assertEqual(report["glass"]["presented"], 1)
        self.assertEqual(report["glass"]["coalesced"], 2)
        self.assertEqual(report["opaque"]["presented"], 0)
        self.assertEqual(report["opaque"]["closed_before_feedback"], 1)


if __name__ == "__main__":
    unittest.main()
