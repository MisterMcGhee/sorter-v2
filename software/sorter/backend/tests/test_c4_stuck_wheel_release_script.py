from __future__ import annotations

import json

import pytest

from scripts import c4_stuck_wheel_release


def test_release_probe_defaults_to_dry_run_without_network(monkeypatch, capsys) -> None:
    def fail_request(*_args, **_kwargs):
        raise AssertionError("dry run must not touch the backend")

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fail_request)

    args = c4_stuck_wheel_release.parse_args([])
    assert c4_stuck_wheel_release.run_probe(args) == 0

    output = capsys.readouterr().out
    assert "contact-break-micro" in output
    assert '"stepper_deg"' in output


def test_release_plan_stage_is_net_zero_and_bounded() -> None:
    strokes = c4_stuck_wheel_release.build_plan(stage_index=1)

    assert len(strokes) == 6
    assert round(sum(stroke.output_deg for stroke in strokes), 6) == 0.0
    assert max(abs(stroke.output_deg) for stroke in strokes) == 0.5
    assert max(stroke.speed for stroke in strokes) == 700


def test_release_execute_requires_confirmations_before_network(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        c4_stuck_wheel_release,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    args = c4_stuck_wheel_release.parse_args(["--execute", "--stage", "1"])

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="confirm-live-c4"):
        c4_stuck_wheel_release.run_probe(args)

    assert calls == []


def test_release_preflight_runs_passive_checks_only(monkeypatch, capsys) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [
                    {
                        "role": "feeder",
                        "device_name": "FEEDER MB",
                        "supports_stepper_cancel": True,
                    }
                ],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)

    args = c4_stuck_wheel_release.parse_args(["--preflight"])
    assert c4_stuck_wheel_release.run_probe(args) == 0

    output = capsys.readouterr().out
    assert "control_boards" in output
    assert calls == [
        ("GET", "/health", None),
        ("GET", "/api/system/status", None),
        ("GET", "/api/hardware-config/control-boards/live", None),
        ("GET", "/api/hardware-config/carousel/live", None),
    ]


def test_release_preflight_can_require_safe_supervisor(monkeypatch, capsys) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/supervisor/status":
            return {"ok": True, "manual_stop_safe": True}
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)

    args = c4_stuck_wheel_release.parse_args(
        ["--preflight", "--require-supervisor-safe"]
    )
    assert c4_stuck_wheel_release.run_probe(args) == 0

    output = capsys.readouterr().out
    assert "supervisor" in output
    assert calls[-1] == ("GET", "/api/supervisor/status", None)


def test_release_preflight_refuses_unsafe_supervisor(monkeypatch) -> None:
    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/supervisor/status":
            return {"ok": True}
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)

    args = c4_stuck_wheel_release.parse_args(
        ["--preflight", "--require-supervisor-safe"]
    )
    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="manual_stop_safe"):
        c4_stuck_wheel_release.run_probe(args)


def test_release_preflight_cannot_execute(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        c4_stuck_wheel_release,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    args = c4_stuck_wheel_release.parse_args(["--preflight", "--execute", "--stage", "1"])

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="mutually exclusive"):
        c4_stuck_wheel_release.run_probe(args)

    assert calls == []


def test_release_execute_stage_runs_preflight_pause_and_strokes(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [
                    {
                        "role": "feeder",
                        "device_name": "FEEDER MB",
                        "supports_stepper_cancel": True,
                    }
                ],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/feeder/detect/carousel":
            return {"ok": True, "candidate_bboxes": []}
        if path == "/api/supervisor/status":
            return {"ok": True, "manual_stop_safe": True}
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)

    args = c4_stuck_wheel_release.parse_args(
        [
            "--execute",
            "--stage",
            "1",
            "--confirm-live-c4",
            "STUCK-WHEEL",
            "--confirm-firmware-cancel",
            "CANCEL-FLASHED",
            "--run-id",
            "unit",
            "--out-root",
            str(tmp_path),
            "--stroke-stop-timeout",
            "1.25",
        ]
    )

    assert c4_stuck_wheel_release.run_probe(args) == 0

    assert calls[:3] == [
        ("GET", "/health", None),
        ("GET", "/api/system/status", None),
        ("GET", "/api/hardware-config/control-boards/live", None),
    ]
    assert calls[3] == ("GET", "/api/hardware-config/carousel/live", None)
    move_calls = [call for call in calls if call[1] == "/stepper/move-degrees"]
    assert len(move_calls) == 6
    assert all(call[2]["stepper"] == "c_channel_4" for call in move_calls)
    assert (tmp_path / "run_unit" / "timeline.json").exists()


def test_release_execute_uses_short_stroke_stop_timeout(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    wait_timeouts: list[float] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/feeder/detect/carousel":
            return {"ok": True, "candidate_bboxes": []}
        if path == "/api/supervisor/status":
            return {"ok": True, "manual_stop_safe": True}
        return {"ok": True}

    def fake_wait_for_stopped(base_url: str, *, timeout: float, poll_s: float = 0.05):
        wait_timeouts.append(timeout)
        return {"ok": True, "stepper_stopped": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)
    monkeypatch.setattr(c4_stuck_wheel_release, "_wait_for_stopped", fake_wait_for_stopped)

    args = c4_stuck_wheel_release.parse_args(
        [
            "--execute",
            "--stage",
            "1",
            "--confirm-live-c4",
            "STUCK-WHEEL",
            "--confirm-firmware-cancel",
            "CANCEL-FLASHED",
            "--stroke-stop-timeout",
            "1.25",
            "--out-root",
            str(tmp_path),
        ]
    )

    assert c4_stuck_wheel_release.run_probe(args) == 0

    assert wait_timeouts == [1.25] * 6


def test_release_execute_can_explicitly_skip_supervisor_check_for_standalone(
    monkeypatch, tmp_path
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/feeder/detect/carousel":
            return {"ok": True, "candidate_bboxes": []}
        return {"ok": True}

    def fake_wait_for_stopped(base_url: str, *, timeout: float, poll_s: float = 0.05):
        return {"ok": True, "stepper_stopped": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)
    monkeypatch.setattr(c4_stuck_wheel_release, "_wait_for_stopped", fake_wait_for_stopped)

    args = c4_stuck_wheel_release.parse_args(
        [
            "--execute",
            "--stage",
            "1",
            "--confirm-live-c4",
            "STUCK-WHEEL",
            "--confirm-firmware-cancel",
            "CANCEL-FLASHED",
            "--skip-supervisor-check",
            "STANDALONE-BACKEND",
            "--out-root",
            str(tmp_path),
        ]
    )

    assert c4_stuck_wheel_release.run_probe(args) == 0
    assert not any(call[1] == "/api/supervisor/status" for call in calls)


def test_release_execute_stops_stepper_if_stop_poll_times_out(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        return {"ok": True}

    def fake_wait_for_stopped(base_url: str, *, timeout: float, poll_s: float = 0.05):
        raise c4_stuck_wheel_release.ProbeError("not stopped")

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)
    monkeypatch.setattr(c4_stuck_wheel_release, "_wait_for_stopped", fake_wait_for_stopped)

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="not stopped"):
        c4_stuck_wheel_release._execute_stroke(
            "http://test",
            c4_stuck_wheel_release.build_plan(stage_index=1)[0],
            timeout=5.0,
            stroke_stop_timeout=1.25,
        )

    assert calls[-1] == ("POST", "/stepper/stop", {"stepper": "c_channel_4"})


def test_release_execute_writes_artifacts_when_stroke_fails(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        calls.append((method, path, params))
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/supervisor/status":
            return {"ok": True, "manual_stop_safe": True}
        if path == "/api/feeder/detect/carousel":
            return {"ok": True, "candidate_bboxes": []}
        return {"ok": True}

    def fake_wait_for_stopped(base_url: str, *, timeout: float, poll_s: float = 0.05):
        raise c4_stuck_wheel_release.ProbeError("not stopped")

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)
    monkeypatch.setattr(c4_stuck_wheel_release, "_wait_for_stopped", fake_wait_for_stopped)

    args = c4_stuck_wheel_release.parse_args(
        [
            "--execute",
            "--stage",
            "1",
            "--confirm-live-c4",
            "STUCK-WHEEL",
            "--confirm-firmware-cancel",
            "CANCEL-FLASHED",
            "--run-id",
            "unit-failed",
            "--out-root",
            str(tmp_path),
        ]
    )

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="not stopped"):
        c4_stuck_wheel_release.run_probe(args)

    run_dir = tmp_path / "run_unit-failed"
    timeline = json.loads((run_dir / "timeline.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    assert any(entry["type"] == "run_error" for entry in timeline)
    assert summary["failed"] is True
    assert summary["error"] == "not stopped"
    assert ("POST", "/stepper/stop", {"stepper": "c_channel_4"}) in calls
    assert ("POST", "/pause", None) in calls


def test_release_execute_can_confirm_each_stroke(monkeypatch, tmp_path) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/feeder/detect/carousel":
            return {"ok": True, "candidate_bboxes": []}
        if path == "/api/supervisor/status":
            return {"ok": True, "manual_stop_safe": True}
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)
    monkeypatch.setattr("builtins.input", fake_input)

    args = c4_stuck_wheel_release.parse_args(
        [
            "--execute",
            "--stage",
            "1",
            "--confirm-each-stroke",
            "--confirm-live-c4",
            "STUCK-WHEEL",
            "--confirm-firmware-cancel",
            "CANCEL-FLASHED",
            "--run-id",
            "unit-confirm",
            "--out-root",
            str(tmp_path),
        ]
    )

    assert c4_stuck_wheel_release.run_probe(args) == 0

    assert len(prompts) == 6
    assert "contact-break-micro.1.cw" in prompts[0]


def test_release_prompt_after_stroke_can_stop_when_released(monkeypatch, tmp_path) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "r"

    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/feeder/detect/carousel":
            return {"ok": True, "candidate_bboxes": []}
        if path == "/api/supervisor/status":
            return {"ok": True, "manual_stop_safe": True}
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)
    monkeypatch.setattr("builtins.input", fake_input)

    args = c4_stuck_wheel_release.parse_args(
        [
            "--execute",
            "--stage",
            "1",
            "--prompt-after-stroke",
            "--confirm-live-c4",
            "STUCK-WHEEL",
            "--confirm-firmware-cancel",
            "CANCEL-FLASHED",
            "--run-id",
            "unit-released",
            "--out-root",
            str(tmp_path),
        ]
    )

    assert c4_stuck_wheel_release.run_probe(args) == 0

    timeline = json.loads((tmp_path / "run_unit-released" / "timeline.json").read_text())
    summary = json.loads((tmp_path / "run_unit-released" / "summary.json").read_text())
    move_entries = [entry for entry in timeline if entry["type"] == "stroke"]
    observations = [entry for entry in timeline if entry["type"] == "operator_observation"]
    result = [entry for entry in timeline if entry["type"] == "run_result"][-1]
    assert len(prompts) == 1
    assert len(move_entries) == 1
    assert observations[0]["payload"]["decision"] == "released"
    assert result["payload"]["stopped_early_reason"] == "released"
    assert summary["strokes_executed"] == 1
    assert summary["released"] is True
    assert summary["released_after_stroke"] == "contact-break-micro.1.cw"
    assert summary["executed_strokes"][0]["label"] == "contact-break-micro.1.cw"


def test_release_prompt_after_stroke_fails_closed_when_stdin_closes(monkeypatch) -> None:
    def closed_input(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", closed_input)

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="stdin closed"):
        c4_stuck_wheel_release._prompt_after_stroke(
            c4_stuck_wheel_release.build_plan(stage_index=1)[0]
        )


def test_release_capture_frames_records_images_in_timeline(monkeypatch, tmp_path) -> None:
    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [{"role": "feeder", "supports_stepper_cancel": True}],
            }
        if path == "/api/hardware-config/carousel/live":
            return {"ok": True, "stepper_stopped": True}
        if path == "/api/feeder/detect/carousel":
            return {"ok": True, "candidate_bboxes": []}
        if path == "/api/supervisor/status":
            return {"ok": True, "manual_stop_safe": True}
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)
    monkeypatch.setattr(
        c4_stuck_wheel_release,
        "_fetch_single_jpeg",
        lambda *_args, **_kwargs: b"\xff\xd8frame\xff\xd9",
    )

    args = c4_stuck_wheel_release.parse_args(
        [
            "--execute",
            "--stage",
            "1",
            "--capture-frames",
            "--confirm-live-c4",
            "STUCK-WHEEL",
            "--confirm-firmware-cancel",
            "CANCEL-FLASHED",
            "--run-id",
            "unit-frames",
            "--out-root",
            str(tmp_path),
        ]
    )

    assert c4_stuck_wheel_release.run_probe(args) == 0

    run_dir = tmp_path / "run_unit-frames"
    timeline = json.loads((run_dir / "timeline.json").read_text())
    frames = [entry for entry in timeline if entry["type"] == "frame"]
    assert len(frames) == 8
    assert all(entry["payload"]["ok"] is True for entry in frames)
    assert (run_dir / "frames" / "before.jpg").read_bytes() == b"\xff\xd8frame\xff\xd9"


def test_release_confirm_each_stroke_fails_closed_when_stdin_closes(monkeypatch) -> None:
    def closed_input(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", closed_input)

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="stdin closed"):
        c4_stuck_wheel_release._confirm_stroke(
            c4_stuck_wheel_release.build_plan(stage_index=1)[0]
        )


def test_release_preflight_refuses_feeder_without_cancel_capability(monkeypatch) -> None:
    def fake_request_json(
        base_url: str,
        method: str,
        path: str,
        *,
        params=None,
        timeout: float,
    ):
        if path == "/api/system/status":
            return {"ok": True, "hardware_state": "ready"}
        if path == "/api/hardware-config/control-boards/live":
            return {
                "ok": True,
                "boards": [
                    {
                        "role": "feeder",
                        "device_name": "FEEDER MB",
                        "supports_stepper_cancel": False,
                    }
                ],
            }
        return {"ok": True}

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fake_request_json)

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="stepper_cancel"):
        c4_stuck_wheel_release._require_ready_and_stopped("http://test", timeout=1.0)


def test_release_report_summarizes_previous_runs_without_network(monkeypatch, tmp_path, capsys) -> None:
    def fail_request(*_args, **_kwargs):
        raise AssertionError("report mode must not touch the backend")

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fail_request)

    first = tmp_path / "run_first"
    first.mkdir()
    (first / "summary.json").write_text(
        json.dumps(
            {
                "strokes_executed": 3,
                "last_stroke": "contact-break-micro.1.cw-return",
                "executed_strokes": [
                    {"label": "contact-break-micro.1.cw", "speed": 700},
                    {"label": "contact-break-micro.1.ccw-cross", "speed": 700},
                    {"label": "contact-break-micro.1.cw-return", "speed": 700},
                ],
                "released": True,
                "released_after_stroke": "contact-break-micro.1.cw-return",
                "aborted": False,
                "frames_captured": 4,
                "frame_errors": [],
                "operator_observations": [
                    {
                        "after_stroke": "contact-break-micro.1.cw-return",
                        "decision": "released",
                        "note": "r",
                    }
                ],
            }
        )
    )
    second = tmp_path / "run_second"
    second.mkdir()
    (second / "summary.json").write_text(
        json.dumps(
            {
                "strokes_executed": 6,
                "last_stroke": "contact-break-micro.2.cw-return",
                "executed_strokes": [],
                "released": False,
                "aborted": False,
                "frames_captured": 0,
            }
        )
    )

    args = c4_stuck_wheel_release.parse_args(["--report", "--out-root", str(tmp_path)])
    assert c4_stuck_wheel_release.run_probe(args) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["runs_seen"] == 2
    assert report["released_runs"] == 1
    assert report["best_release"]["run_id"] == "first"
    assert report["best_release"]["released_stroke"]["speed"] == 700


def test_release_report_cannot_execute(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        c4_stuck_wheel_release,
        "_request_json",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    args = c4_stuck_wheel_release.parse_args(["--report", "--execute", "--stage", "1"])

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="cannot be combined"):
        c4_stuck_wheel_release.run_probe(args)

    assert calls == []


def test_release_verify_firmware_artifacts_without_network(monkeypatch, tmp_path, capsys) -> None:
    def fail_request(*_args, **_kwargs):
        raise AssertionError("firmware verification must not touch the backend")

    monkeypatch.setattr(c4_stuck_wheel_release, "_request_json", fail_request)

    feeder = tmp_path / "build-feeder"
    distribution = tmp_path / "build-distribution"
    feeder.mkdir()
    distribution.mkdir()
    (feeder / "sorter_interface_firmware.uf2").write_bytes(
        b"stepper_cancel CANCEL FEEDER c_channel_1_rotor carousel"
    )
    (distribution / "sorter_interface_firmware.uf2").write_bytes(
        b"stepper_cancel CANCEL DISTRIBUTION chute_stepper"
    )

    args = c4_stuck_wheel_release.parse_args(
        ["--verify-firmware-artifacts", "--firmware-dir", str(tmp_path)]
    )
    assert c4_stuck_wheel_release.run_probe(args) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["artifacts"]["feeder"]["ok"] is True
    assert report["artifacts"]["distribution"]["ok"] is True
    assert len(report["artifacts"]["feeder"]["sha256"]) == 64


def test_release_verify_firmware_artifacts_fails_on_missing_marker(tmp_path) -> None:
    feeder = tmp_path / "build-feeder"
    distribution = tmp_path / "build-distribution"
    feeder.mkdir()
    distribution.mkdir()
    (feeder / "sorter_interface_firmware.uf2").write_bytes(
        b"stepper_cancel CANCEL FEEDER c_channel_1_rotor carousel"
    )
    (distribution / "sorter_interface_firmware.uf2").write_bytes(
        b"stepper_cancel CANCEL DISTRIBUTION"
    )

    args = c4_stuck_wheel_release.parse_args(
        ["--verify-firmware-artifacts", "--firmware-dir", str(tmp_path)]
    )

    with pytest.raises(c4_stuck_wheel_release.ProbeError, match="firmware artifact"):
        c4_stuck_wheel_release.run_probe(args)
