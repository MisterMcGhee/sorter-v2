#!/usr/bin/env python3
"""Guarded C4 stuck-wheel release probe.

Default mode is dry-run only: it prints the staged movement plan and does not
touch the backend. Live execution intentionally requires an explicit stage and
two confirmation flags so a broad escalation cannot start by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_SUPERVISOR_URL = "http://127.0.0.1:8001"
DEFAULT_OUT_ROOT = Path("/tmp/c4_stuck_wheel_release")
DEFAULT_FIRMWARE_DIR = (
    Path(__file__).resolve().parents[3]
    / "firmware"
    / "sorter_interface_firmware"
)
C4_STEPPER = "c_channel_4"
GEAR_RATIO = 130.0 / 12.0
MICROSTEPS_PER_STEPPER_DEG = (200 * 8) / 360.0
CONFIRM_LIVE_VALUE = "STUCK-WHEEL"
CONFIRM_FIRMWARE_VALUE = "CANCEL-FLASHED"
CONFIRM_ALL_VALUE = "ESCALATE-C4"
SKIP_SUPERVISOR_VALUE = "STANDALONE-BACKEND"
FIRMWARE_ARTIFACTS = {
    "feeder": {
        "path": Path("build-feeder") / "sorter_interface_firmware.uf2",
        "required_markers": (
            b"stepper_cancel",
            b"CANCEL",
            b"FEEDER",
            b"c_channel_1_rotor",
            b"carousel",
        ),
    },
    "distribution": {
        "path": Path("build-distribution") / "sorter_interface_firmware.uf2",
        "required_markers": (
            b"stepper_cancel",
            b"CANCEL",
            b"DISTRIBUTION",
            b"chute_stepper",
        ),
    },
}


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Stage:
    index: int
    name: str
    amplitude_output_deg: float
    cycles: int
    speed: int
    min_speed: int
    acceleration: int
    settle_ms: int


@dataclass(frozen=True)
class Stroke:
    stage: int
    label: str
    output_deg: float
    stepper_deg: float
    estimated_microsteps: int
    speed: int
    min_speed: int
    acceleration: int
    settle_ms: int


STAGES: tuple[Stage, ...] = (
    Stage(1, "contact-break-micro", 0.25, 2, 700, 16, 1800, 300),
    Stage(2, "low-rock", 0.50, 2, 950, 16, 2600, 300),
    Stage(3, "medium-rock", 0.85, 3, 1250, 16, 3600, 350),
    Stage(4, "firm-rock", 1.25, 3, 1600, 16, 4800, 400),
    Stage(5, "last-resort-small-kick", 1.75, 2, 1900, 16, 6000, 450),
)


def _url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    base = base_url.rstrip("/")
    if not params:
        return f"{base}{path}"
    return f"{base}{path}?{parse.urlencode(params)}"


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    req = request.Request(_url(base_url, path, params), method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise ProbeError(f"{method} {path} -> HTTP {exc.code}: {raw}") from exc
    except OSError as exc:
        raise ProbeError(f"{method} {path} failed: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"{method} {path} returned non-JSON: {raw[:200]}") from exc
    return payload if isinstance(payload, dict) else {"value": payload}


def _require_supervisor_safe(supervisor_url: str, *, timeout: float) -> dict[str, Any]:
    status = _request_json(
        supervisor_url,
        "GET",
        "/api/supervisor/status",
        timeout=timeout,
    )
    if not bool(status.get("manual_stop_safe")):
        raise ProbeError(
            "supervisor does not report manual_stop_safe=true; restart the supervisor before live C4 probing"
        )
    return status


def _fetch_single_jpeg(base_url: str, *, timeout: float) -> bytes:
    url = _url(
        base_url,
        "/api/cameras/feed/carousel",
        {"dashboard": "false", "layer": "annotated"},
    )
    try:
        with request.urlopen(url, timeout=timeout) as response:
            chunk = b""
            while True:
                data = response.read(4096)
                if not data:
                    break
                chunk += data
                start = chunk.find(b"\xff\xd8")
                end = chunk.find(b"\xff\xd9", start + 2 if start != -1 else 0)
                if start != -1 and end != -1:
                    return chunk[start : end + 2]
                if len(chunk) > 3_000_000:
                    raise ProbeError("carousel frame stream exceeded 3MB without a complete JPEG")
    except OSError as exc:
        raise ProbeError(f"fetch carousel frame failed: {exc}") from exc
    raise ProbeError("carousel frame stream ended before a complete JPEG")


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _capture_frame(base_url: str, run_dir: Path, label: str, *, timeout: float) -> dict[str, Any]:
    frame_dir = run_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    dest = frame_dir / f"{_safe_name(label)}.jpg"
    try:
        data = _fetch_single_jpeg(base_url, timeout=timeout)
        dest.write_bytes(data)
        return {"ok": True, "label": label, "path": str(dest), "bytes": len(data)}
    except ProbeError as exc:
        return {"ok": False, "label": label, "error": str(exc)}


def _stepper_deg_for_output(output_deg: float) -> float:
    return float(output_deg) * GEAR_RATIO


def _microsteps_for_stepper_deg(stepper_deg: float) -> int:
    return int(round(abs(stepper_deg) * MICROSTEPS_PER_STEPPER_DEG))


def _stage_strokes(stage: Stage) -> list[Stroke]:
    strokes: list[Stroke] = []
    amp = float(stage.amplitude_output_deg)
    for cycle in range(1, stage.cycles + 1):
        # Net zero over the three strokes, but the middle stroke crosses
        # through the previous contact patch and tends to break static friction.
        for suffix, output_deg in (
            ("cw", amp),
            ("ccw-cross", -2.0 * amp),
            ("cw-return", amp),
        ):
            stepper_deg = _stepper_deg_for_output(output_deg)
            strokes.append(
                Stroke(
                    stage=stage.index,
                    label=f"{stage.name}.{cycle}.{suffix}",
                    output_deg=round(output_deg, 6),
                    stepper_deg=round(stepper_deg, 6),
                    estimated_microsteps=_microsteps_for_stepper_deg(stepper_deg),
                    speed=stage.speed,
                    min_speed=stage.min_speed,
                    acceleration=stage.acceleration,
                    settle_ms=stage.settle_ms,
                )
            )
    return strokes


def build_plan(stage_index: int | None = None, *, all_stages: bool = False) -> list[Stroke]:
    if all_stages:
        stages = STAGES
    else:
        if stage_index is None:
            return [stroke for stage in STAGES for stroke in _stage_strokes(stage)]
        stage = next((candidate for candidate in STAGES if candidate.index == stage_index), None)
        if stage is None:
            raise ProbeError(f"unknown stage {stage_index}; valid stages are 1-{len(STAGES)}")
        stages = (stage,)
    return [stroke for stage in stages for stroke in _stage_strokes(stage)]


def _print_plan(strokes: list[Stroke]) -> None:
    print(json.dumps([asdict(stroke) for stroke in strokes], indent=2))


def _wait_for_stopped(base_url: str, *, timeout: float, poll_s: float = 0.05) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_payload = _request_json(
            base_url,
            "GET",
            "/api/hardware-config/carousel/live",
            timeout=timeout,
        )
        if bool(last_payload.get("stepper_stopped")):
            return last_payload
        time.sleep(poll_s)
    raise ProbeError(f"C4 did not report stopped within {timeout:.1f}s; last={last_payload}")


def _require_ready_and_stopped(base_url: str, *, timeout: float) -> dict[str, Any]:
    health = _request_json(base_url, "GET", "/health", timeout=timeout)
    system_status = _request_json(base_url, "GET", "/api/system/status", timeout=timeout)
    hardware_state = system_status.get("hardware_state")
    if hardware_state != "ready":
        raise ProbeError(f"hardware_state must be ready before live C4 probe, got {hardware_state!r}")

    control_boards = _request_json(
        base_url,
        "GET",
        "/api/hardware-config/control-boards/live",
        timeout=timeout,
    )
    boards = control_boards.get("boards")
    if not isinstance(boards, list):
        raise ProbeError("live control board response has no boards list")
    feeder_boards = [
        board
        for board in boards
        if isinstance(board, dict) and board.get("role") == "feeder"
    ]
    if not feeder_boards:
        raise ProbeError("no live feeder control board found")
    unsafe_feeders = [
        board
        for board in feeder_boards
        if not bool(board.get("supports_stepper_cancel"))
    ]
    if unsafe_feeders:
        raise ProbeError(f"feeder firmware does not report stepper_cancel: {unsafe_feeders}")

    live = _request_json(base_url, "GET", "/api/hardware-config/carousel/live", timeout=timeout)
    if not bool(live.get("stepper_stopped")):
        raise ProbeError(f"C4 is not stopped before probe start: {live}")

    return {
        "health": health,
        "system_status": system_status,
        "control_boards": control_boards,
        "live": live,
    }


def _detect_carousel(base_url: str, *, timeout: float) -> dict[str, Any]:
    try:
        return _request_json(base_url, "POST", "/api/feeder/detect/carousel", timeout=timeout)
    except ProbeError as exc:
        return {"ok": False, "error": str(exc)}


def _execute_stroke(
    base_url: str,
    stroke: Stroke,
    *,
    timeout: float,
    stroke_stop_timeout: float,
) -> dict[str, Any]:
    params = {
        "stepper": C4_STEPPER,
        "degrees": stroke.stepper_deg,
        "speed": stroke.speed,
        "min_speed": stroke.min_speed,
        "acceleration": stroke.acceleration,
    }
    response = _request_json(base_url, "POST", "/stepper/move-degrees", params=params, timeout=timeout)
    try:
        stopped = _wait_for_stopped(base_url, timeout=stroke_stop_timeout)
    except Exception:
        _request_json(base_url, "POST", "/stepper/stop", params={"stepper": C4_STEPPER}, timeout=timeout)
        raise
    time.sleep(max(0, stroke.settle_ms) / 1000.0)
    return {"move": response, "stopped": stopped}


def _confirm_stroke(stroke: Stroke) -> None:
    prompt = (
        f"About to execute {stroke.label}: output_deg={stroke.output_deg}, "
        f"stepper_deg={stroke.stepper_deg}, speed={stroke.speed}. "
        "Press Enter to continue, or Ctrl-C to abort: "
    )
    try:
        input(prompt)
    except EOFError as exc:
        raise ProbeError("interactive stroke confirmation failed: stdin closed") from exc


def _prompt_after_stroke(stroke: Stroke) -> dict[str, str]:
    prompt = (
        f"After {stroke.label}: Enter=continue, r=released/stop, "
        "a=abort/stop, or type a note to continue: "
    )
    try:
        raw = input(prompt)
    except EOFError as exc:
        raise ProbeError("post-stroke observation prompt failed: stdin closed") from exc

    response = raw.strip()
    normalized = response.lower()
    if normalized in {"r", "released", "done", "gelöst", "geloest"}:
        decision = "released"
    elif normalized in {"a", "abort", "stop", "s", "abbrechen"}:
        decision = "abort"
    else:
        decision = "continue"
    return {"decision": decision, "note": response}


def _summarize_timeline(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    strokes = [entry for entry in timeline if entry.get("type") == "stroke"]
    observations = [
        entry for entry in timeline if entry.get("type") == "operator_observation"
    ]
    frames = [entry for entry in timeline if entry.get("type") == "frame"]
    frame_errors = [
        entry
        for entry in frames
        if not bool((entry.get("payload") or {}).get("ok"))
    ]
    run_result = next(
        (
            entry.get("payload") or {}
            for entry in reversed(timeline)
            if entry.get("type") == "run_result"
        ),
        {},
    )
    stopped_early_reason = run_result.get("stopped_early_reason")
    run_error = run_result.get("error")
    released_observation = next(
        (
            entry
            for entry in observations
            if (entry.get("payload") or {}).get("decision") == "released"
        ),
        None,
    )
    abort_observation = next(
        (
            entry
            for entry in observations
            if (entry.get("payload") or {}).get("decision") == "abort"
        ),
        None,
    )
    return {
        "strokes_executed": len(strokes),
        "last_stroke": (
            (strokes[-1].get("stroke") or {}).get("label") if strokes else None
        ),
        "executed_strokes": [
            entry.get("stroke") or {}
            for entry in strokes
        ],
        "stopped_early_reason": stopped_early_reason,
        "failed": run_error is not None,
        "error": run_error,
        "released": released_observation is not None,
        "released_after_stroke": (
            released_observation.get("after_stroke")
            if released_observation is not None
            else None
        ),
        "aborted": abort_observation is not None,
        "aborted_after_stroke": (
            abort_observation.get("after_stroke")
            if abort_observation is not None
            else None
        ),
        "operator_observations": [
            {
                "after_stroke": entry.get("after_stroke"),
                **(entry.get("payload") or {}),
            }
            for entry in observations
        ],
        "frames_requested": len(frames),
        "frames_captured": len(frames) - len(frame_errors),
        "frame_errors": [
            {
                "label": entry.get("label"),
                "error": (entry.get("payload") or {}).get("error"),
            }
            for entry in frame_errors
        ],
    }


def _stroke_by_label(summary: dict[str, Any], label: str | None) -> dict[str, Any] | None:
    if not label:
        return None
    for stroke in summary.get("executed_strokes") or []:
        if isinstance(stroke, dict) and stroke.get("label") == label:
            return stroke
    return None


def _load_run_summaries(out_root: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for summary_path in sorted(out_root.glob("run_*/summary.json")):
        run_dir = summary_path.parent
        try:
            summary = json.loads(summary_path.read_text())
        except Exception as exc:
            runs.append(
                {
                    "run_id": run_dir.name.removeprefix("run_"),
                    "run_dir": str(run_dir),
                    "ok": False,
                    "error": str(exc),
                }
            )
            continue
        if not isinstance(summary, dict):
            runs.append(
                {
                    "run_id": run_dir.name.removeprefix("run_"),
                    "run_dir": str(run_dir),
                    "ok": False,
                    "error": "summary.json is not an object",
                }
            )
            continue
        released_after = summary.get("released_after_stroke")
        runs.append(
            {
                "run_id": run_dir.name.removeprefix("run_"),
                "run_dir": str(run_dir),
                "ok": True,
                "released": bool(summary.get("released")),
                "released_after_stroke": released_after,
                "released_stroke": _stroke_by_label(summary, released_after),
                "aborted": bool(summary.get("aborted")),
                "aborted_after_stroke": summary.get("aborted_after_stroke"),
                "strokes_executed": int(summary.get("strokes_executed") or 0),
                "last_stroke": summary.get("last_stroke"),
                "stopped_early_reason": summary.get("stopped_early_reason"),
                "frames_captured": int(summary.get("frames_captured") or 0),
                "frame_errors": summary.get("frame_errors") or [],
                "operator_observations": summary.get("operator_observations") or [],
            }
        )
    return runs


def _build_report(out_root: Path) -> dict[str, Any]:
    runs = _load_run_summaries(out_root)
    valid_runs = [run for run in runs if run.get("ok")]
    released_runs = [run for run in valid_runs if run.get("released")]
    best_release = None
    if released_runs:
        best_release = sorted(
            released_runs,
            key=lambda run: (
                int(run.get("strokes_executed") or 0),
                str(run.get("run_id") or ""),
            ),
        )[0]
    return {
        "out_root": str(out_root),
        "runs_seen": len(runs),
        "valid_runs": len(valid_runs),
        "released_runs": len(released_runs),
        "best_release": best_release,
        "runs": runs,
    }


def _verify_firmware_artifacts(firmware_dir: Path) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    overall_ok = True
    for role, spec in FIRMWARE_ARTIFACTS.items():
        path = firmware_dir / spec["path"]
        if not path.exists():
            artifacts[role] = {
                "ok": False,
                "path": str(path),
                "error": "missing artifact",
            }
            overall_ok = False
            continue

        data = path.read_bytes()
        required_markers: tuple[bytes, ...] = spec["required_markers"]
        missing = [
            marker.decode("ascii", errors="replace")
            for marker in required_markers
            if marker not in data
        ]
        ok = not missing
        if not ok:
            overall_ok = False
        artifacts[role] = {
            "ok": ok,
            "path": str(path),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "missing_markers": missing,
        }

    return {
        "ok": overall_ok,
        "firmware_dir": str(firmware_dir),
        "artifacts": artifacts,
    }


def run_probe(args: argparse.Namespace) -> int:
    if args.verify_firmware_artifacts:
        if args.execute or args.preflight or args.report:
            raise ProbeError(
                "--verify-firmware-artifacts cannot be combined with --execute, --preflight, or --report"
            )
        report = _verify_firmware_artifacts(Path(args.firmware_dir))
        print(json.dumps(report, indent=2, sort_keys=True))
        if not report["ok"]:
            raise ProbeError("firmware artifact verification failed")
        return 0

    if args.report:
        if args.execute or args.preflight:
            raise ProbeError("--report cannot be combined with --execute or --preflight")
        print(json.dumps(_build_report(Path(args.out_root)), indent=2, sort_keys=True))
        return 0

    if args.preflight and args.execute:
        raise ProbeError("--preflight and --execute are mutually exclusive")

    if args.preflight:
        payload = _require_ready_and_stopped(str(args.base_url), timeout=float(args.timeout))
        if args.require_supervisor_safe:
            payload["supervisor"] = _require_supervisor_safe(
                str(args.supervisor_url),
                timeout=float(args.timeout),
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.execute:
        if args.confirm_live_c4 != CONFIRM_LIVE_VALUE:
            raise ProbeError(f"--execute requires --confirm-live-c4 {CONFIRM_LIVE_VALUE}")
        if args.confirm_firmware_cancel != CONFIRM_FIRMWARE_VALUE:
            raise ProbeError(f"--execute requires --confirm-firmware-cancel {CONFIRM_FIRMWARE_VALUE}")
        if args.all_stages and args.confirm_all_stages != CONFIRM_ALL_VALUE:
            raise ProbeError(f"--all-stages requires --confirm-all-stages {CONFIRM_ALL_VALUE}")
        if args.stage is None and not args.all_stages:
            raise ProbeError("--execute requires --stage N, or --all-stages with the extra confirmation")

    strokes = build_plan(args.stage, all_stages=bool(args.all_stages))
    if not args.execute:
        _print_plan(strokes)
        return 0

    base_url = str(args.base_url)
    timeout = float(args.timeout)
    stroke_stop_timeout = float(args.stroke_stop_timeout)
    require_supervisor_safe = args.skip_supervisor_check != SKIP_SUPERVISOR_VALUE
    run_dir = Path(args.out_root) / f"run_{args.run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    preflight = _require_ready_and_stopped(base_url, timeout=timeout)
    if require_supervisor_safe:
        preflight["supervisor"] = _require_supervisor_safe(
            str(args.supervisor_url),
            timeout=timeout,
        )
    _request_json(base_url, "POST", "/pause", timeout=timeout)

    timeline: list[dict[str, Any]] = [
        {"type": "preflight", "payload": preflight},
    ]
    if args.capture_frames:
        timeline.append(
            {
                "type": "frame",
                "label": "before",
                "payload": _capture_frame(base_url, run_dir, "before", timeout=timeout),
            }
        )
    timeline.append({"type": "before_detection", "payload": _detect_carousel(base_url, timeout=timeout)})
    (run_dir / "plan.json").write_text(json.dumps([asdict(stroke) for stroke in strokes], indent=2))

    stopped_early_reason: str | None = None
    run_error: str | None = None
    try:
        for index, stroke in enumerate(strokes, start=1):
            print(f"[{index}/{len(strokes)}] {stroke.label} stepper_deg={stroke.stepper_deg}")
            if args.confirm_each_stroke:
                _confirm_stroke(stroke)
            result = _execute_stroke(
                base_url,
                stroke,
                timeout=timeout,
                stroke_stop_timeout=stroke_stop_timeout,
            )
            timeline.append({"type": "stroke", "stroke": asdict(stroke), "payload": result})
            if args.capture_frames:
                timeline.append(
                    {
                        "type": "frame",
                        "label": f"after_{index:02d}_{stroke.label}",
                        "payload": _capture_frame(
                            base_url,
                            run_dir,
                            f"after_{index:02d}_{stroke.label}",
                            timeout=timeout,
                        ),
                    }
                )
            timeline.append(
                {
                    "type": "detection",
                    "after_stroke": stroke.label,
                    "payload": _detect_carousel(base_url, timeout=timeout),
                }
            )
            if args.prompt_after_stroke:
                observation = _prompt_after_stroke(stroke)
                timeline.append(
                    {
                        "type": "operator_observation",
                        "after_stroke": stroke.label,
                        "payload": observation,
                    }
                )
                if observation["decision"] != "continue":
                    stopped_early_reason = observation["decision"]
                    print(f"Stopping remaining strokes: {stopped_early_reason}")
                    break
    except Exception as exc:
        run_error = str(exc)
        timeline.append(
            {
                "type": "run_error",
                "payload": {"error": run_error},
            }
        )
    finally:
        try:
            _request_json(base_url, "POST", "/stepper/stop", params={"stepper": C4_STEPPER}, timeout=timeout)
        finally:
            _request_json(base_url, "POST", "/pause", timeout=timeout)

    if args.capture_frames:
        timeline.append(
            {
                "type": "frame",
                "label": "after",
                "payload": _capture_frame(base_url, run_dir, "after", timeout=timeout),
            }
        )
    timeline.append({"type": "after_detection", "payload": _detect_carousel(base_url, timeout=timeout)})
    timeline.append(
        {
            "type": "run_result",
            "payload": {
                "stopped_early_reason": stopped_early_reason,
                "error": run_error,
            },
        }
    )
    summary = _summarize_timeline(timeline)
    (run_dir / "timeline.json").write_text(json.dumps(timeline, indent=2))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Wrote C4 release probe data to {run_dir}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if run_error is not None:
        raise ProbeError(run_error)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guarded C4 stuck-wheel release probe.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--supervisor-url", default=DEFAULT_SUPERVISOR_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--stroke-stop-timeout", type=float, default=3.0)
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--firmware-dir", default=str(DEFAULT_FIRMWARE_DIR))
    parser.add_argument("--stage", type=int, choices=range(1, len(STAGES) + 1))
    parser.add_argument("--all-stages", action="store_true")
    parser.add_argument("--verify-firmware-artifacts", action="store_true")
    parser.add_argument("--report", action="store_true", help="Summarize previous run_*/summary.json files.")
    parser.add_argument("--preflight", action="store_true", help="Run passive live safety checks only.")
    parser.add_argument("--require-supervisor-safe", action="store_true")
    parser.add_argument(
        "--skip-supervisor-check",
        default="",
        help=f"Bypass live supervisor safety check only with {SKIP_SUPERVISOR_VALUE}.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--capture-frames", action="store_true")
    parser.add_argument("--confirm-each-stroke", action="store_true")
    parser.add_argument("--prompt-after-stroke", action="store_true")
    parser.add_argument("--confirm-live-c4", default="")
    parser.add_argument("--confirm-firmware-cancel", default="")
    parser.add_argument("--confirm-all-stages", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_probe(args)
    except ProbeError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
