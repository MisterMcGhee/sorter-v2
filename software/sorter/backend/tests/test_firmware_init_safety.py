from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from hardware.sorter_interface import SorterInterface
from irl.config import _require_stepper_cancel_firmware


FIRMWARE_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "firmware"
    / "sorter_interface_firmware"
    / "sorter_interface_firmware.cpp"
)


def _function_body(source: str, name: str) -> str:
    signature = f"void {name}("
    start = source.index(signature)
    brace_start = source.index("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start : index + 1]
    raise AssertionError(f"Could not find body for {name}")


def test_firmware_init_cancels_stepper_motion_before_enabling_drivers() -> None:
    source = FIRMWARE_SOURCE.read_text()
    body = _function_body(source, "initialize_hardware")

    cancel_index = body.index("steppers[i].cancel();")
    initialize_index = body.index("tmc_drivers[i].initialize();")
    enable_index = body.index("tmc_drivers[i].enableDriver(true);")

    assert cancel_index < initialize_index
    assert cancel_index < enable_index


def test_firmware_exposes_stepper_cancel_command() -> None:
    source = FIRMWARE_SOURCE.read_text()

    assert '{"CANCEL", "", "", 0, VAL_stepper_channel, CMDH_stepper_cancel}' in source
    assert "void CMDH_stepper_cancel(const BusMessage *msg, BusMessage *resp)" in source
    assert '\\"firmware_protocol\\":2,\\"stepper_cancel\\":true' in source


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload


class _Bus:
    def __init__(self, board_info: dict):
        self.board_info = board_info

    def send_command(self, address, command, channel, payload):
        return _Response(json.dumps(self.board_info).encode("utf-8"))


class _Logger:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, message, *_args, **_kwargs):
        self.errors.append(str(message))


def test_sorter_interface_reports_stepper_cancel_capability() -> None:
    interface = SorterInterface(
        _Bus(
            {
                "device_name": "FEEDER MB",
                "firmware_protocol": 2,
                "stepper_cancel": True,
                "stepper_count": 4,
                "digital_input_count": 4,
                "digital_output_count": 5,
                "servo_count": 0,
            }
        ),
        address=0,
        gc=SimpleNamespace(logger=_Logger()),
    )

    assert interface.supports_stepper_cancel is True


def test_backend_rejects_boards_without_stepper_cancel_capability() -> None:
    logger = _Logger()
    board = SimpleNamespace(
        interface=SimpleNamespace(supports_stepper_cancel=False),
        identity=SimpleNamespace(
            device_name="FEEDER MB",
            port="/dev/cu.usbmodem-test",
            address=0,
            role="feeder",
        ),
    )

    with pytest.raises(RuntimeError, match="missing stepper_cancel capability"):
        _require_stepper_cancel_firmware(SimpleNamespace(logger=logger), [board])

    assert logger.errors
