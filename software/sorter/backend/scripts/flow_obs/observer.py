"""Flow Observer — emit per-second window metrics for the C2/C3/C4 pipeline.

Polls the backend's read-only HTTP endpoints once per second and writes one
JSONL record per window to ``out_path``. The records are intentionally
*anonymous* (no per-piece IDs) — they describe the particle flow as a
density/rate process, exactly as
``docs/.../optimization-strategy-research.md`` recommends.

Per window we capture:

    - per-table detection counts (T2/T3/T4) split into drop / transport /
      exit zones, plus a crowding score
    - per-table arrival_rate / exit_rate derived from feeder pulse-count
      deltas (these are observed actions of the runtime, not detections)
    - T4 active_pieces breakdown + state classification:
      STARVED, GOOD_SINGLE, OVERLOADED, UNCLEAR
    - Brickognize fire/empty/timeout deltas

The records are dense, but small (~1 KB each), so a 5-minute observation is
~300 KB. Use ``report.py`` to summarise.

Usage:
    python observer.py SECONDS OUT_PATH RUN_LABEL
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.request

BASE = "http://localhost:8000"
TABLE_ROLES = {"T2": "c_channel_2", "T3": "c_channel_3", "T4": "carousel"}

# State-classification thresholds. Conservative defaults; tune from baseline
# data, don't tune from intuition.
T4_OVERLOADED_THRESHOLD = 2     # active_pieces >= this → OVERLOADED
T4_STARVED_GRACE_S = 4.0        # contiguous "no pieces visible" before STARVED

CROWDING_NEAR_PX = 120.0        # bbox-centre distance below this counts as "near"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as r:
        return json.loads(r.read())


def _post(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _bbox_centre(box: list) -> tuple[float, float]:
    x1, y1, x2, y2 = box[:4]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _crowding(bboxes: list) -> float:
    """Mean nearest-neighbour distance, normalised — lower = more crowded.

    Returns 0.0 when 0 or 1 bbox (no crowding possible). For multi-bbox we
    sum 1 for every pair within ``CROWDING_NEAR_PX`` and divide by the
    total pair count. Result is in [0, 1] where 1.0 == every pair is
    near.
    """
    if len(bboxes) < 2:
        return 0.0
    centres = [_bbox_centre(b) for b in bboxes]
    near = 0
    total = 0
    for i in range(len(centres)):
        for j in range(i + 1, len(centres)):
            dx = centres[i][0] - centres[j][0]
            dy = centres[i][1] - centres[j][1]
            if math.hypot(dx, dy) <= CROWDING_NEAR_PX:
                near += 1
            total += 1
    return near / max(1, total)


def _split_zone(bboxes: list, frame_h: int) -> tuple[int, int, int]:
    """Split bboxes into (drop, transport, exit) buckets by vertical band.

    Heuristic: top third → "drop" (where pieces enter), bottom third →
    "exit" (where pieces leave), middle third → "transport". For C4 this
    is approximate; the drop/intake angles are angular, not axis-aligned.
    We accept the approximation for now — what matters is the *split*
    being consistent across windows so the rate signal is meaningful.
    """
    if not bboxes:
        return (0, 0, 0)
    top = int(frame_h / 3)
    bot = int(frame_h * 2 / 3)
    drop_n = transport_n = exit_n = 0
    for b in bboxes:
        _cx, cy = _bbox_centre(b)
        if cy < top:
            drop_n += 1
        elif cy < bot:
            transport_n += 1
        else:
            exit_n += 1
    return (drop_n, transport_n, exit_n)


def _classify_t4(
    active_pieces: list[dict],
    starved_streak_s: float,
) -> str:
    """Assign a coarse state class to the T4 (classification channel) view.

    Reads ``active_pieces`` from /api/classification-channel/debug rather
    than raw YOLO detections — the runtime's zone manager is more stable
    than per-frame YOLO bbox counts.
    """
    n = len(active_pieces)
    if n == 0:
        return "T4_STARVED" if starved_streak_s >= T4_STARVED_GRACE_S else "T4_EMPTY"
    if n >= T4_OVERLOADED_THRESHOLD:
        return "T4_OVERLOADED"
    # Exactly 1 piece: GOOD_SINGLE if it's heading to drop, UNCLEAR otherwise.
    piece = active_pieces[0]
    angle = piece.get("zone_center_deg")
    if isinstance(angle, (int, float)):
        return "T4_GOOD_SINGLE"
    return "T4_UNCLEAR"


def main(seconds: int, out_path: str, run_label: str) -> None:
    end_t = time.monotonic() + seconds

    # Baselines for delta computations (feeder pulses, brickognize counters)
    prev_counters: dict[str, int] = {}
    starved_since: float | None = None
    poll_count = 0
    fp = open(out_path, "w")
    print(f"observer: writing {out_path} for {seconds}s (label={run_label})")

    try:
        while time.monotonic() < end_t:
            tick_start = time.monotonic()
            now_wall = time.time()
            window: dict = {
                "ts": now_wall,
                "run_label": run_label,
                "poll_idx": poll_count,
            }

            # --- per-table detection windows ---
            for table_label, role in TABLE_ROLES.items():
                try:
                    det = _post(f"/api/feeder/detect/{role}")
                except Exception as exc:
                    window[f"{table_label}_err"] = str(exc)
                    continue
                bboxes = det.get("candidate_bboxes") or []
                tracks = det.get("track_count", 0) or 0
                _w, h = det.get("frame_resolution") or (1920, 1080)
                drop_n, transport_n, exit_n = _split_zone(bboxes, h)
                window[table_label] = {
                    "n_total": len(bboxes),
                    "n_drop": drop_n,
                    "n_transport": transport_n,
                    "n_exit": exit_n,
                    "tracks": tracks,
                    "crowding": round(_crowding(bboxes), 3),
                }

            # --- T4 active-pieces (runtime view) ---
            try:
                dbg = _get("/api/classification-channel/debug")
                active = dbg.get("active_pieces") or []
                positions = dbg.get("positions") or {}
                window["T4_active"] = {
                    "n": len(active),
                    "hood_uuid": positions.get("hood_piece_uuid"),
                    "positioning_uuid": positions.get("positioning_piece_uuid"),
                    "exit_uuid": positions.get("exit_piece_uuid"),
                    "angles": [
                        p.get("zone_center_deg") for p in active
                        if isinstance(p.get("zone_center_deg"), (int, float))
                    ],
                    "statuses": [p.get("classification_status") for p in active],
                }
            except Exception as exc:
                window["T4_active_err"] = str(exc)
                active = []

            # --- starvation streak ---
            if len(active) == 0:
                if starved_since is None:
                    starved_since = tick_start
                starved_streak = tick_start - starved_since
            else:
                starved_since = None
                starved_streak = 0.0
            window["T4_starved_streak_s"] = round(starved_streak, 2)
            window["T4_state"] = _classify_t4(active, starved_streak)

            # --- runtime counters for rates ---
            try:
                stats = _get("/runtime-stats")["payload"]
            except Exception as exc:
                window["runtime_err"] = str(exc)
                fp.write(json.dumps(window) + "\n")
                fp.flush()
                poll_count += 1
                time.sleep(max(0.0, 1.0 - (time.monotonic() - tick_start)))
                continue

            counts = stats.get("counts", {})
            feeder = stats.get("feeder", {})
            pulses = feeder.get("pulse_counts", {})

            # Rates we care about: pulses-per-second per channel + cls/dist/mlt
            sources = {
                "ch1_sent": pulses.get("ch1", {}).get("sent", 0),
                "ch2_sent": pulses.get("ch2_normal", {}).get("sent", 0) + pulses.get("ch2_precise", {}).get("sent", 0),
                "ch3_sent": pulses.get("ch3_normal", {}).get("sent", 0) + pulses.get("ch3_precise", {}).get("sent", 0),
                "seen": counts.get("pieces_seen", 0),
                "classified": counts.get("classified", 0),
                "unknown": counts.get("unknown", 0),
                "multi_drop_fail": counts.get("multi_drop_fail", 0),
                "distributed": counts.get("distributed", 0),
                "recognize_fired": counts.get("recognize_fired_total", 0),
                "recognize_skipped_dwell": counts.get("recognize_skipped_carousel_dwell", 0),
                "recognize_skipped_traversal": counts.get("recognize_skipped_carousel_traversal", 0),
                "brickognize_empty": counts.get("brickognize_empty_result", 0),
                "brickognize_timeout": counts.get("brickognize_timeout_total", 0),
            }
            deltas: dict[str, int] = {}
            for key, val in sources.items():
                deltas[key] = val - prev_counters.get(key, val) if poll_count else 0
                prev_counters[key] = val
            window["delta"] = deltas
            window["cumulative"] = sources

            window["lifecycle"] = stats.get("lifecycle_state")

            fp.write(json.dumps(window) + "\n")
            fp.flush()
            poll_count += 1
            elapsed = time.monotonic() - tick_start
            time.sleep(max(0.0, 1.0 - elapsed))
    finally:
        fp.close()
        print(f"observer: done after {poll_count} polls -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: observer.py SECONDS OUT_PATH RUN_LABEL", file=sys.stderr)
        sys.exit(2)
    main(int(sys.argv[1]), sys.argv[2], sys.argv[3])
