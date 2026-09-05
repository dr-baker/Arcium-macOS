#!/usr/bin/env python3
"""Summarize Arcium's privacy-safe measurement events in a local JSON trace."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics


def summarize(trace: dict) -> dict:
    samples: dict[str, list[float]] = {}
    for event in trace.get("traceEvents", []):
        if event.get("name") != "Arcium.MRU.Presented":
            continue
        args = event.get("args", {})
        latency = args.get("latency_us")
        if (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(latency)
            or latency < 0
            or type(args.get("glass")) is not bool
            or type(args.get("opening")) is not bool
        ):
            continue
        key = ("glass" if args["glass"] else "opaque") + "." + (
            "open" if args["opening"] else "cycle"
        )
        samples.setdefault(key, []).append(latency / 1000)
    result = {}
    for key, values in sorted(samples.items()):
        values.sort()
        result[key] = {
            "count": len(values),
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[math.ceil(0.95 * len(values)) - 1], 3),
            "max_ms": round(values[-1], 3),
        }
    return result


def outcomes(trace: dict) -> dict:
    names = ("presented", "coalesced", "closed_before_feedback", "invalid_timestamp")
    result: dict[str, dict[str, int]] = {}
    for event in trace.get("traceEvents", []):
        if event.get("name") != "Arcium.MRU.PresentationOutcome":
            continue
        args = event.get("args", {})
        value = args.get("outcome")
        if type(value) is not int or not 0 <= value < len(names):
            continue
        if type(args.get("glass")) is not bool:
            continue
        mode = "glass" if args["glass"] else "opaque"
        counts = result.setdefault(mode, dict.fromkeys(names, 0))
        counts[names[value]] += 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        trace = json.loads(args.trace.read_text())
        current = summarize(trace)
        baseline = (
            json.loads(args.baseline.read_text())
            if args.baseline
            else None
        )
        report = {"presentation": current, "outcomes": outcomes(trace)}
        if baseline is not None:
            report["baseline_presentation"] = summarize(baseline)
            report["baseline_outcomes"] = outcomes(baseline)
    except (OSError, ValueError, AttributeError, TypeError) as error:
        parser.error(str(error))
    report["limitations"] = (
        "Successful browser-compositor feedback only. Check coalesced and "
        "closed requests alongside latency. Trace boundaries can truncate requests. "
        "These are neither GPU execution times nor all-frame smoothness. "
        "Keep build, workload, display, and run order with each trace."
    )
    print(json.dumps(report, indent=2))
    if not current:
        parser.exit(1, "No Arcium.MRU.Presented samples in this trace.\n")


if __name__ == "__main__":
    main()
