from __future__ import annotations

from types import SimpleNamespace

from server.routers import hardware


def test_live_control_boards_reports_stepper_cancel_capability(monkeypatch) -> None:
    board = SimpleNamespace(
        identity=SimpleNamespace(
            family="skr_pico",
            role="feeder",
            device_name="FEEDER MB",
            port="/dev/cu.usbmodem-test",
            address=0,
        ),
        interface=SimpleNamespace(
            supports_stepper_cancel=True,
            _board_info={"firmware_protocol": 2},
        ),
        logical_stepper_names=("c_channel_1_rotor", "carousel"),
    )
    monkeypatch.setattr(
        hardware.shared_state,
        "getActiveIRL",
        lambda: SimpleNamespace(control_boards={"feeder": board}),
    )
    monkeypatch.setattr(hardware.shared_state, "hardware_state", "ready")

    payload = hardware.get_live_control_boards()

    assert payload["ok"] is True
    assert payload["hardware_state"] == "ready"
    assert payload["boards"][0]["role"] == "feeder"
    assert payload["boards"][0]["supports_stepper_cancel"] is True
    assert payload["boards"][0]["firmware_protocol"] == 2
