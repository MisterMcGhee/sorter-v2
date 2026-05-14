"""Flow Runner — capture full per-run config + invoke the observer.

Usage:
    python runner.py SECONDS LABEL [--note "..."]

For each run:
  1. Snapshot every relevant backend setting (max_zones, gates, dwell, etc.)
  2. Launch ``observer.py`` for ``SECONDS`` seconds, writing to a fresh log
  3. Write a ``<label>_meta.json`` alongside the observer log

The log + meta pair is the unit the strategy doc calls a "run" — every
later comparison goes through these files, not through ad-hoc curl loops.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "http://localhost:8000"
LOG_DIR = Path("/Users/mneuhaus/Workspace/LegoSorter/sorter-v2/docs/lab/flow_runs")


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as r:
        return json.loads(r.read())


def _post(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def capture_config() -> dict:
    """Snapshot the runtime configuration that the strategy doc cares about."""
    snap: dict = {"captured_at": datetime.utcnow().isoformat() + "Z"}
    try:
        dbg = _get("/api/classification-channel/debug")
        snap["c4_config"] = dbg.get("config", {})
        snap["c4_gates"] = dbg.get("gates", {})
    except Exception as exc:
        snap["c4_err"] = str(exc)
    try:
        det = _get("/api/feeder/detection-config")
        snap["detection_algorithm_by_role"] = det.get("algorithm_by_role")
    except Exception as exc:
        snap["detection_err"] = str(exc)
    try:
        sysstat = _get("/api/system/status")
        snap["hardware_state"] = sysstat
    except Exception as exc:
        snap["system_err"] = str(exc)
    try:
        stats = _get("/runtime-stats")["payload"]
        snap["lifecycle"] = stats.get("lifecycle_state")
        snap["baseline_counts"] = stats.get("counts", {})
    except Exception as exc:
        snap["stats_err"] = str(exc)
    return snap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", type=int)
    ap.add_argument("label")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"{ts}_{args.label}.jsonl"
    meta_path = LOG_DIR / f"{ts}_{args.label}.meta.json"

    print(f"runner: capturing pre-run config snapshot...")
    pre_config = capture_config()
    started_at = time.time()

    observer_py = Path(__file__).parent / "observer.py"
    cmd = ["uv", "run", "--python", "python3", "python", str(observer_py), str(args.seconds), str(log_path), args.label]
    print(f"runner: launching observer ({args.seconds}s)")
    completed = subprocess.run(cmd, check=False)
    finished_at = time.time()

    print(f"runner: capturing post-run stats")
    post_config = capture_config()
    meta = {
        "label": args.label,
        "note": args.note,
        "started_at_wall": started_at,
        "finished_at_wall": finished_at,
        "duration_s": round(finished_at - started_at, 1),
        "log_path": str(log_path),
        "pre_config": pre_config,
        "post_config": post_config,
        "observer_exit": completed.returncode,
    }
    with open(meta_path, "w") as fp:
        json.dump(meta, fp, indent=2)
    print(f"runner: meta written to {meta_path}")
    print(f"runner: log written to   {log_path}")


if __name__ == "__main__":
    main()
