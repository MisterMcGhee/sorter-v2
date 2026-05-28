from dataclasses import dataclass


@dataclass
class GoToAngleConfig:
    # +1 carries pieces toward the exit (camera-clockwise = forward motor
    # direction). Flip to -1 if a channel's stepper is wired the other way.
    forward_direction_sign: int = 1
    move_speed_usteps_per_s: int = 4000
    move_acceleration_usteps_per_s2: int = 2500
    # Normal advance per move when pieces are present but none is at the exit
    # yet — carries the train forward toward the exit zone (output degrees).
    advance_output_deg: float = 30.0
    # Ignore moves smaller than this (noise) and clamp any single move to the
    # max so a bad angle calc can never spin a channel wildly.
    min_move_output_deg: float = 2.0
    max_move_output_deg: float = 120.0
    # Cooldown after a normal advance move before the channel is re-evaluated.
    settle_after_move_ms: int = 250
    # Precise (at-exit) mode. Instead of shoving a piece past the exit edge in
    # one move, nudge it forward one small fixed angle at a time, pausing
    # between pulses so the downstream channel can confirm receipt before we
    # push again. Mirrors the reactive flow's precise pulsing.
    precise_pulse_output_deg: float = 1.0
    precise_pulse_pause_ms: int = 200
    # Bulk feeder (c_channel_1) has no vision zones: nudge it forward by a fixed
    # amount whenever c_channel_2's drop zone is clear.
    ch1_advance_output_deg: float = 20.0
    ch1_settle_after_move_ms: int = 800
    # Gate c_channel_3 forward motion on the downstream classification channel
    # being ready to accept a piece (avoids double-drops into the same sector).
    gate_ch3_on_classification_ready: bool = True
    enable_ch1: bool = True
    enable_ch2: bool = True
    enable_ch3: bool = True

    # Jitter unstick for a piece lingering in the exit-only sub-arc (precise
    # zone excluded — pieces parked there are normal hand-offs to C4). After
    # ``jitter_exit_dwell_ms`` of continuous exit-only dwell, oscillate up to
    # 3 times with ``jitter_pause_ms`` between attempts. Reset on leave.
    # Perception path only (see flow.py:_jitter_tick).
    jitter_exit_dwell_ms: int = 1500
    jitter_pause_ms: int = 350
    jitter_amplitude_motor_deg: float = 6.0
    jitter_cycles: int = 8
    jitter_speed_usteps_per_s: int = 5000
    jitter_accel_usteps_per_s2: int = 100000


_DEFAULTS = GoToAngleConfig()

FIELD_META: list[dict] = [
    {"key": "forward_direction_sign", "label": "Forward direction sign (+1/-1)", "type": "int", "default": _DEFAULTS.forward_direction_sign},
    {"key": "move_speed_usteps_per_s", "label": "Move speed (µsteps/s)", "type": "int", "default": _DEFAULTS.move_speed_usteps_per_s},
    {"key": "move_acceleration_usteps_per_s2", "label": "Move acceleration (µsteps/s²)", "type": "int", "default": _DEFAULTS.move_acceleration_usteps_per_s2},
    {"key": "advance_output_deg", "label": "Normal advance (output deg)", "type": "float", "default": _DEFAULTS.advance_output_deg},
    {"key": "min_move_output_deg", "label": "Min move (output deg)", "type": "float", "default": _DEFAULTS.min_move_output_deg},
    {"key": "max_move_output_deg", "label": "Max move clamp (output deg)", "type": "float", "default": _DEFAULTS.max_move_output_deg},
    {"key": "settle_after_move_ms", "label": "Settle after advance (ms)", "type": "int", "default": _DEFAULTS.settle_after_move_ms},
    {"key": "precise_pulse_output_deg", "label": "Precise pulse angle (output deg)", "type": "float", "default": _DEFAULTS.precise_pulse_output_deg},
    {"key": "precise_pulse_pause_ms", "label": "Precise pulse pause between pulses (ms)", "type": "int", "default": _DEFAULTS.precise_pulse_pause_ms},
    {"key": "ch1_advance_output_deg", "label": "C1 bulk advance (output deg)", "type": "float", "default": _DEFAULTS.ch1_advance_output_deg},
    {"key": "ch1_settle_after_move_ms", "label": "C1 settle after move (ms)", "type": "int", "default": _DEFAULTS.ch1_settle_after_move_ms},
    {"key": "gate_ch3_on_classification_ready", "label": "Gate C3 on classification ready", "type": "bool", "default": _DEFAULTS.gate_ch3_on_classification_ready},
    {"key": "enable_ch1", "label": "Enable C1 (bulk)", "type": "bool", "default": _DEFAULTS.enable_ch1},
    {"key": "enable_ch2", "label": "Enable C2", "type": "bool", "default": _DEFAULTS.enable_ch2},
    {"key": "enable_ch3", "label": "Enable C3", "type": "bool", "default": _DEFAULTS.enable_ch3},
    {"key": "jitter_exit_dwell_ms", "label": "Jitter: exit dwell before trigger (ms)", "type": "int", "default": _DEFAULTS.jitter_exit_dwell_ms},
    {"key": "jitter_pause_ms", "label": "Jitter: pause between attempts (ms)", "type": "int", "default": _DEFAULTS.jitter_pause_ms},
    {"key": "jitter_amplitude_motor_deg", "label": "Jitter amplitude (motor deg)", "type": "float", "default": _DEFAULTS.jitter_amplitude_motor_deg},
    {"key": "jitter_cycles", "label": "Jitter cycles per burst", "type": "int", "default": _DEFAULTS.jitter_cycles},
    {"key": "jitter_speed_usteps_per_s", "label": "Jitter speed (\u00b5steps/s)", "type": "int", "default": _DEFAULTS.jitter_speed_usteps_per_s},
    {"key": "jitter_accel_usteps_per_s2", "label": "Jitter accel (\u00b5steps/s\u00b2)", "type": "int", "default": _DEFAULTS.jitter_accel_usteps_per_s2},
]


def configFromDict(d: dict) -> GoToAngleConfig:
    cfg = GoToAngleConfig()
    for meta in FIELD_META:
        k = meta["key"]
        if k not in d:
            continue
        raw = d[k]
        try:
            if meta["type"] == "int":
                setattr(cfg, k, int(raw))
            elif meta["type"] == "bool":
                setattr(cfg, k, bool(raw))
            else:
                setattr(cfg, k, float(raw))
        except (TypeError, ValueError):
            pass
    return cfg


def configToDict(cfg: GoToAngleConfig) -> dict[str, object]:
    return {meta["key"]: getattr(cfg, meta["key"]) for meta in FIELD_META}
