"""Flow Report — turn observer JSONL into per-run KPIs.

Reads one observer log file (one window per line, ``observer.py`` output)
and computes the KPIs from the strategy document:

  - good_parts_per_min   (= classified per min over the run window)
  - distributed_per_min
  - T4 state share (% time STARVED / GOOD_SINGLE / OVERLOADED / UNCLEAR)
  - per-table N_mean / N_max / arrival_rate / exit_rate / crowding
  - Brickognize empty-rate
  - simple transfer correlation (ch2_sent / ch3_sent / seen / classified)

Optionally compares two logs (A vs B), printing distributional deltas so
single-test fluke doesn't masquerade as a real improvement.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def _load(path: Path) -> list[dict]:
    out: list[dict] = []
    with open(path) as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _agg_table(windows: list[dict], key: str) -> dict:
    """Aggregate a single table's per-window counts."""
    n_totals = []
    n_drops = []
    n_exits = []
    crowdings = []
    for w in windows:
        t = w.get(key)
        if not isinstance(t, dict):
            continue
        n_totals.append(t.get("n_total", 0))
        n_drops.append(t.get("n_drop", 0))
        n_exits.append(t.get("n_exit", 0))
        crowdings.append(t.get("crowding", 0.0))
    if not n_totals:
        return {}
    return {
        "n_total_mean": round(statistics.mean(n_totals), 2),
        "n_total_median": statistics.median(n_totals),
        "n_total_max": max(n_totals),
        "n_drop_mean": round(statistics.mean(n_drops), 2),
        "n_exit_mean": round(statistics.mean(n_exits), 2),
        "crowding_mean": round(statistics.mean(crowdings), 3),
        "crowding_max": round(max(crowdings), 3),
    }


def _summarise(windows: list[dict]) -> dict:
    if not windows:
        return {"empty": True}
    duration_s = windows[-1]["ts"] - windows[0]["ts"]
    if duration_s <= 0:
        duration_s = max(1, len(windows))
    minutes = duration_s / 60.0

    # Cumulative diffs use last - first since each window stores running totals
    first = windows[0].get("cumulative", {})
    last = windows[-1].get("cumulative", {})
    total = {k: last.get(k, 0) - first.get(k, 0) for k in last}

    state_counts = Counter(w.get("T4_state", "T4_UNCLEAR") for w in windows)

    # Rate computations per minute (whole run)
    rates_per_min = {
        f"{k}_per_min": round(total.get(k, 0) / minutes, 2)
        for k in (
            "seen",
            "classified",
            "distributed",
            "unknown",
            "multi_drop_fail",
            "recognize_fired",
            "ch1_sent",
            "ch2_sent",
            "ch3_sent",
        )
    }

    return {
        "duration_s": round(duration_s, 1),
        "windows": len(windows),
        "T2": _agg_table(windows, "T2"),
        "T3": _agg_table(windows, "T3"),
        "T4": _agg_table(windows, "T4"),
        "T4_state_share": {
            k: round(100.0 * v / len(windows), 1)
            for k, v in sorted(state_counts.items(), key=lambda x: -x[1])
        },
        "totals": total,
        "rates_per_min": rates_per_min,
        "brickognize_empty_total": total.get("brickognize_empty", 0),
        "brickognize_timeout_total": total.get("brickognize_timeout", 0),
        # KPI of interest: pieces cleanly classified+dropped per minute.
        # Approximation: "classified" pieces that reach distributed.
        "good_parts_per_min": rates_per_min.get("classified_per_min", 0),
    }


def _print_summary(label: str, summary: dict) -> None:
    print(f"\n=== {label} ===")
    if summary.get("empty"):
        print("  (empty log)")
        return
    print(f"  duration={summary['duration_s']}s windows={summary['windows']}")
    print(f"  GOAL: good_parts_per_min = {summary['good_parts_per_min']:.1f} (target ≥ 8)")
    print("  T4 state share:")
    for state, pct in summary["T4_state_share"].items():
        print(f"    {state}: {pct}%")
    print("  per-table N_total mean / max:")
    for tbl in ("T2", "T3", "T4"):
        t = summary.get(tbl, {})
        if t:
            print(
                f"    {tbl}: mean={t.get('n_total_mean')} max={t.get('n_total_max')} "
                f"crowding_mean={t.get('crowding_mean')} n_exit_mean={t.get('n_exit_mean')}"
            )
    rpm = summary["rates_per_min"]
    print("  rates per minute:")
    for k in ("seen", "classified", "distributed", "multi_drop_fail", "recognize_fired", "ch1_sent", "ch2_sent", "ch3_sent"):
        print(f"    {k}/min = {rpm.get(f'{k}_per_min', 0)}")
    print(f"  brickognize_empty={summary['brickognize_empty_total']} timeout={summary['brickognize_timeout_total']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", type=Path)
    args = ap.parse_args()

    for log_path in args.logs:
        windows = _load(log_path)
        summary = _summarise(windows)
        _print_summary(str(log_path.name), summary)


if __name__ == "__main__":
    main()
