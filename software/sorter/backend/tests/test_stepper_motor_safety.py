import struct

import pytest

from hardware.sorter_interface import InterfaceCommandCode, StepperMotor


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _GC:
    logger = _Logger()


class _Response:
    def __init__(self, payload: bytes = b""):
        self.payload = payload


class _Device:
    def __init__(self, stopped_values=None, cancel_supported=True):
        self.stopped_values = list(stopped_values or [True])
        self.cancel_supported = cancel_supported
        self.commands = []

    def send_command(self, command, channel, payload):
        self.commands.append((command, channel, payload))
        if command == InterfaceCommandCode.STEPPER_IS_STOPPED:
            value = self.stopped_values.pop(0) if self.stopped_values else self.stopped_values[-1] if self.stopped_values else True
            return _Response(bytes([1 if value else 0]))
        if command == InterfaceCommandCode.STEPPER_MOVE_AT_SPEED:
            return _Response(bytes([1]))
        if command == InterfaceCommandCode.STEPPER_CANCEL:
            if not self.cancel_supported:
                raise RuntimeError("cancel unsupported")
            return _Response(b"")
        if command == InterfaceCommandCode.STEPPER_DRV_SET_ENABLED:
            return _Response(b"")
        return _Response(bytes([1]))


def _stepper(stopped_values=None):
    stepper = StepperMotor(_Device(stopped_values), channel=3, gc=_GC())
    stepper._enabled = False
    stepper._enable_abort_timeout_s = 0.01
    stepper._halt_timeout_s = 0.01
    return stepper


def test_enable_aborts_firmware_motion_before_enabling_driver():
    stepper = _stepper([False, True])

    stepper.enabled = True

    commands = stepper._dev.commands
    cancel_commands = [
        command
        for command, _channel, payload in commands
        if command == InterfaceCommandCode.STEPPER_CANCEL
    ]
    enable_payloads = [
        payload
        for command, _channel, payload in commands
        if command == InterfaceCommandCode.STEPPER_DRV_SET_ENABLED
    ]
    assert cancel_commands == [InterfaceCommandCode.STEPPER_CANCEL]
    assert enable_payloads == [struct.pack("<?", False), struct.pack("<?", True)]


def test_enable_refuses_driver_when_firmware_motion_does_not_stop():
    stepper = _stepper([False, False, False, False])

    with pytest.raises(RuntimeError):
        stepper.enabled = True

    assert [
        payload
        for command, _channel, payload in stepper._dev.commands
        if command == InterfaceCommandCode.STEPPER_DRV_SET_ENABLED
    ] == [struct.pack("<?", False)]


def test_enable_checks_firmware_even_when_local_state_thinks_enabled():
    device = _Device([False, True])
    stepper = StepperMotor(device, channel=3, gc=_GC())
    stepper._enable_abort_timeout_s = 0.01

    stepper.enabled = True

    assert (InterfaceCommandCode.STEPPER_CANCEL, 3, b"") in device.commands
    assert (
        InterfaceCommandCode.STEPPER_DRV_SET_ENABLED,
        3,
        struct.pack("<?", False),
    ) in device.commands
    assert device.commands[-1] == (
        InterfaceCommandCode.STEPPER_DRV_SET_ENABLED,
        3,
        struct.pack("<?", True),
    )


def test_halt_disables_driver_and_aborts_firmware_motion():
    stepper = StepperMotor(_Device([False, True]), channel=3, gc=_GC())
    stepper._halt_timeout_s = 0.01

    assert stepper.halt(disable_driver=True)

    commands = stepper._dev.commands
    assert commands[0] == (
        InterfaceCommandCode.STEPPER_DRV_SET_ENABLED,
        3,
        struct.pack("<?", False),
    )
    assert (InterfaceCommandCode.STEPPER_CANCEL, 3, b"") in commands


def test_halt_sends_driver_disable_even_when_local_state_thinks_disabled():
    stepper = _stepper([True])

    assert stepper.halt(disable_driver=True)

    assert stepper._dev.commands[0] == (
        InterfaceCommandCode.STEPPER_DRV_SET_ENABLED,
        3,
        struct.pack("<?", False),
    )


def test_halt_falls_back_to_zero_speed_for_old_firmware():
    stepper = StepperMotor(
        _Device([False, True], cancel_supported=False),
        channel=3,
        gc=_GC(),
    )
    stepper._halt_timeout_s = 0.01

    assert stepper.halt(disable_driver=True)

    assert (
        InterfaceCommandCode.STEPPER_MOVE_AT_SPEED,
        3,
        struct.pack("<i", 0),
    ) in stepper._dev.commands
