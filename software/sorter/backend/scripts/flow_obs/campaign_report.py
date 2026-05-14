"""Multi-run campaign report — aggregate metrics across several flow_obs logs.

Reads every ``*.jsonl`` matching a glob, computes per-run KPIs (via
``report._summarise``), and prints summary distributions: median, p10,
p90, range. This is the unit of comparison the strategy doc recommends
instead of single test results.

Usage:
    python campaign_report.py "glob_pattern" [--label-prefix BASELINE]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

# Reuse summariser to keep KPI logic in one place
from report import _load, _summarise  # noqa: E402


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _format_dist(values: list[float]) -> str:
    if not values:
        return "n=0"
    return (
        f"n={len(values)} "
        f"med={statistics.median(values):.2f} "
        f"mean={statistics.mean(values):.2f} "
        f"p10={_percentile(values, 0.1):.2f} "
        f"p90={_percentile(values, 0.9):.2f} "
        f"min={min(values):.2f} max={max(values):.2f}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", help="Glob, e.g. '/path/baseline_*.jsonl'")
    ap.add_argument("--label-prefix", default="")
    args = ap.parse_args()

    from glob import glob
    paths = [Path(p) for p in sorted(glob(args.pattern))]
    if not paths:
        print(f"no logs match {args.pattern}", end="\n")
        return

    print(f"campaign: {len(paths)} runs from {paths[0].parent}")
    rows = []
    for p in paths:
        windows = _load(p)
        summary = _summarise(windows)
        rows.append((p.name, summary))

    # Distributions of key KPIs
    print(f"\n=== KPI distributions across {len(rows)} runs ===")
    for kpi in (
        "good_parts_per_min",
    ):
        vals = [s.get(kpi, 0) for _, s in rows if not s.get("empty")]
        print(f"  {kpi:30s} : {_format_dist(vals)}")

    for kpi in (
        "seen_per_min",
        "classified_per_min",
        "distributed_per_min",
        "multi_drop_fail_per_min",
        "recognize_fired_per_min",
        "ch3_sent_per_min",
        "ch2_sent_per_min",
        "ch1_sent_per_min",
    ):
        vals = [s["rates_per_min"].get(kpi, 0) for _, s in rows if not s.get("empty")]
        print(f"  {kpi:30s} : {_format_dist(vals)}")

    # T4 state-share distributions
    states = ["T4_OVERLOADED", "T4_GOOD_SINGLE", "T4_EMPTY", "T4_STARVED", "T4_UNCLEAR"]
    print(f"\n=== T4 state share across runs (% time) ===")
    for state in states:
        vals = [s["T4_state_share"].get(state, 0.0) for _, s in rows if not s.get("empty")]
        print(f"  {state:18s} : {_format_dist(vals)}")

    # Per-table N_total mean distributions
    print(f"\n=== Per-table N_total mean distributions ===")
    for tbl in ("T2", "T3", "T4"):
        vals = [s.get(tbl, {}).get("n_total_mean", 0) for _, s in rows if not s.get("empty")]
        print(f"  {tbl}_n_total_mean    : {_format_dist(vals)}")
        vals = [s.get(tbl, {}).get("crowding_mean", 0) for _, s in rows if not s.get("empty")]
        print(f"  {tbl}_crowding_mean   : {_format_dist(vals)}")

    print(f"\n=== Per-run good_parts_per_min ===")
    for name, s in rows:
        if s.get("empty"):
            continue
        print(f"  {s['good_parts_per_min']:.1f}  ({name})")


if __name__ == "__main__":
    main()
