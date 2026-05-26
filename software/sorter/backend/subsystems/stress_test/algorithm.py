"""Pure logic for the C-channel tracking stress test.

Kept free of hardware/vision/threading imports so it can be unit-tested
without spinning up the rest of the backend. The runner module wires this
together with real steppers and the vision tracker.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


StressTrialStatus = Literal[
    "delivered",
    "exited",
    "track_lost",
    "no_exit",
    "no_piece",
    "skipped",
    "pending",
]


@dataclass
class StressTrialParams:
    speed_microsteps_per_second: int
    pulse_steps: int
    pause_ms: int
    acceleration_microsteps_per_second_sq: int

    def toDict(self) -> dict:
        return {
            "speed_microsteps_per_second": int(self.speed_microsteps_per_second),
            "pulse_steps": int(self.pulse_steps),
            "pause_ms": int(self.pause_ms),
            "acceleration_microsteps_per_second_sq": int(
                self.acceleration_microsteps_per_second_sq
            ),
        }


@dataclass
class StressTrialResult:
    params: StressTrialParams
    status: StressTrialStatus = "pending"
    tracked_global_id: int | None = None
    pulses_fired: int = 0
    duration_s: float = 0.0
    note: str | None = None

    def toDict(self) -> dict:
        return {
            "params": self.params.toDict(),
            "status": self.status,
            "tracked_global_id": self.tracked_global_id,
            "pulses_fired": int(self.pulses_fired),
            "duration_s": float(self.duration_s),
            "note": self.note,
        }


@dataclass
class StressSweepConfig:
    """Inputs that describe the parameter grid the test will walk.

    The user defines a *starting* (aggressive) point and we decrement speed
    while optionally increasing pause to dial back. The sweep is linear: we
    decrement speed first, then for each row of pause we re-sweep speed.
    """

    top_speed: int
    min_speed: int
    speed_step: int
    pulse_steps: int
    start_pause_ms: int = 0
    max_pause_ms: int = 0
    pause_step_ms: int = 0
    acceleration_microsteps_per_second_sq: int = 20000
    # How many *consecutive* tracker observations the piece may be absent
    # from C2 before we call it "track lost". Each observation is a fresh
    # read of the feeder tracker's live global_ids. Bigger = more tolerant
    # of single-frame detection misses.
    track_loss_grace_observations: int = 2

    def __post_init__(self) -> None:
        if self.top_speed <= 0:
            raise ValueError("top_speed must be > 0")
        if self.min_speed <= 0:
            raise ValueError("min_speed must be > 0")
        if self.min_speed > self.top_speed:
            raise ValueError("min_speed must be <= top_speed")
        if self.speed_step <= 0:
            raise ValueError("speed_step must be > 0")
        if self.pulse_steps <= 0:
            raise ValueError("pulse_steps must be > 0")
        if self.start_pause_ms < 0 or self.max_pause_ms < 0:
            raise ValueError("pause_ms values must be >= 0")
        if self.max_pause_ms < self.start_pause_ms:
            raise ValueError("max_pause_ms must be >= start_pause_ms")
        if self.pause_step_ms < 0:
            raise ValueError("pause_step_ms must be >= 0")
        if self.max_pause_ms > self.start_pause_ms and self.pause_step_ms <= 0:
            raise ValueError("pause_step_ms must be > 0 when sweeping pause")
        if self.acceleration_microsteps_per_second_sq <= 0:
            raise ValueError("acceleration must be > 0")
        if self.track_loss_grace_observations < 0:
            raise ValueError("track_loss_grace_observations must be >= 0")


def buildLinearSweep(cfg: StressSweepConfig) -> list[StressTrialParams]:
    """Generate the (pause, speed) grid the test will walk.

    Order: for each pause value (ascending from `start_pause_ms`), sweep
    speed from `top_speed` down to `min_speed`. Aggressive params come
    first so the test surfaces failures early.
    """
    trials: list[StressTrialParams] = []
    pause_values: list[int] = []
    p = cfg.start_pause_ms
    if cfg.max_pause_ms == cfg.start_pause_ms or cfg.pause_step_ms == 0:
        pause_values = [cfg.start_pause_ms]
    else:
        while p <= cfg.max_pause_ms:
            pause_values.append(p)
            p += cfg.pause_step_ms
        if pause_values[-1] != cfg.max_pause_ms:
            pause_values.append(cfg.max_pause_ms)

    for pause_ms in pause_values:
        speed = cfg.top_speed
        while speed >= cfg.min_speed:
            trials.append(
                StressTrialParams(
                    speed_microsteps_per_second=int(speed),
                    pulse_steps=int(cfg.pulse_steps),
                    pause_ms=int(pause_ms),
                    acceleration_microsteps_per_second_sq=int(
                        cfg.acceleration_microsteps_per_second_sq
                    ),
                )
            )
            if speed == cfg.min_speed:
                break
            speed = max(cfg.min_speed, speed - cfg.speed_step)
    return trials


@dataclass
class TrialObservation:
    """Vision observation passed to ``determineNextStatus``.

    Captures enough to decide whether the trial has reached a terminal
    status. Pure data — the runner builds these from the live tracker.

    ``consecutive_misses`` is the number of back-to-back tracker reads
    that have come back without the piece's global_id on c_channel_2 since
    the last sighting. ``grace_observations`` is the operator-configured
    tolerance: as long as misses are within grace, we treat the piece as
    still present.

    ``piece_in_exit_zone_now`` is True when the tracked piece is, right now,
    overlapping the channel's exit sections. Once a piece reaches the exit
    it has travelled the whole channel — that is the success we're looking
    for, regardless of whether it later disappears.

    ``last_seen_in_exit_zone`` records whether, the last time we saw the
    piece, it was in the exit zone. It's a fallback: if the piece vanishes
    between observations (fell off the end before we caught it in-zone) we
    still credit the exit rather than calling it lost.
    """

    consecutive_misses: int
    grace_observations: int
    piece_now_on_c3: bool
    piece_in_exit_zone_now: bool
    last_seen_in_exit_zone: bool
    pulses_fired: int
    max_pulses: int


def determineNextStatus(obs: TrialObservation) -> StressTrialStatus:
    """Decide whether a trial is done after the latest observation.

    Order matters:
    - if the tracked piece appeared on c3, the channels delivered it
      while keeping track the whole way → "delivered".
    - else if the piece is in the exit zone *right now* (still tracked),
      it has made it all the way down the channel → "exited" (success).
      We don't wait for it to disappear — reaching the exit IS the win.
    - else if the tracker has missed the piece on c2 for more than
      ``grace_observations`` consecutive reads, the piece is gone. How we
      classify that depends on *where* it was last seen:
        - if it was last seen in the exit zone, it fell off the end of
          the channel = a clean exit → "exited" (success).
        - otherwise it vanished mid-channel = the vision lost it because
          we ran too fast → "track_lost" (the failure we're hunting).
    - else if we've burned through ``max_pulses`` and the piece is still
      sitting on c2 without ever reaching the exit, the params were too
      gentle to move it off → "no_exit".
    - otherwise the trial is still running.

    Losing a track is an *expected* outcome of a sweep, not an error: it
    just means those params were too aggressive. The runner records it and
    moves on to the next trial.
    """
    if obs.piece_now_on_c3:
        return "delivered"
    if obs.piece_in_exit_zone_now:
        return "exited"
    if obs.consecutive_misses > obs.grace_observations:
        return "exited" if obs.last_seen_in_exit_zone else "track_lost"
    if obs.pulses_fired >= obs.max_pulses:
        return "no_exit"
    return "pending"
