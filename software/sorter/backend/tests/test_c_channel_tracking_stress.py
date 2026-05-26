"""Tests for the C-channel tracking stress test."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import pytest

from subsystems.stress_test import c_channel_tracking as runner_mod
from subsystems.stress_test.algorithm import (
    StressSweepConfig,
    TrialObservation,
    buildLinearSweep,
    determineNextStatus,
)
from subsystems.stress_test.c_channel_tracking import CChannelTrackingStressRunner


# ---------------------------------------------------------------------------
# Pure algorithm tests
# ---------------------------------------------------------------------------


def test_buildLinearSweep_single_pause_walks_speed_down() -> None:
    cfg = StressSweepConfig(
        top_speed=5000,
        min_speed=2000,
        speed_step=1000,
        pulse_steps=500,
    )
    trials = buildLinearSweep(cfg)
    speeds = [t.speed_microsteps_per_second for t in trials]
    assert speeds == [5000, 4000, 3000, 2000]
    assert all(t.pause_ms == 0 for t in trials)
    assert all(t.pulse_steps == 500 for t in trials)


def test_buildLinearSweep_includes_min_speed_when_step_overshoots() -> None:
    cfg = StressSweepConfig(
        top_speed=5000,
        min_speed=2500,
        speed_step=1500,
        pulse_steps=500,
    )
    trials = buildLinearSweep(cfg)
    speeds = [t.speed_microsteps_per_second for t in trials]
    assert speeds == [5000, 3500, 2500]


def test_buildLinearSweep_walks_pause_then_speed() -> None:
    cfg = StressSweepConfig(
        top_speed=4000,
        min_speed=2000,
        speed_step=2000,
        pulse_steps=500,
        start_pause_ms=0,
        max_pause_ms=200,
        pause_step_ms=100,
    )
    trials = buildLinearSweep(cfg)
    pairs = [(t.pause_ms, t.speed_microsteps_per_second) for t in trials]
    assert pairs == [
        (0, 4000), (0, 2000),
        (100, 4000), (100, 2000),
        (200, 4000), (200, 2000),
    ]


def test_buildLinearSweep_rejects_invalid_pauses() -> None:
    with pytest.raises(ValueError):
        StressSweepConfig(
            top_speed=5000,
            min_speed=2000,
            speed_step=1000,
            pulse_steps=500,
            start_pause_ms=100,
            max_pause_ms=50,
        )


def test_determineNextStatus_delivered_takes_priority() -> None:
    # Even if c2 misses look like a loss, a confirmed c3 sighting wins.
    obs = TrialObservation(
        consecutive_misses=99,
        grace_observations=0,
        piece_now_on_c3=True,
        piece_in_exit_zone_now=False,
        last_seen_in_exit_zone=False,
        pulses_fired=3,
        max_pulses=10,
    )
    assert determineNextStatus(obs) == "delivered"


def test_determineNextStatus_exited_when_in_exit_zone_now() -> None:
    # Piece is currently tracked and sitting in the exit zone — it made it
    # all the way down. Success immediately, no waiting for it to vanish.
    obs = TrialObservation(
        consecutive_misses=0,
        grace_observations=2,
        piece_now_on_c3=False,
        piece_in_exit_zone_now=True,
        last_seen_in_exit_zone=True,
        pulses_fired=1,
        max_pulses=10,
    )
    assert determineNextStatus(obs) == "exited"


def test_determineNextStatus_track_lost_when_misses_exceed_grace_mid_channel() -> None:
    obs = TrialObservation(
        consecutive_misses=3,
        grace_observations=2,
        piece_now_on_c3=False,
        piece_in_exit_zone_now=False,
        last_seen_in_exit_zone=False,
        pulses_fired=2,
        max_pulses=10,
    )
    assert determineNextStatus(obs) == "track_lost"


def test_determineNextStatus_exited_when_vanishes_from_exit_zone() -> None:
    # Same miss pattern as track_lost, but the piece was last seen in the
    # exit zone — it fell off the end, which is a clean exit, not a loss.
    obs = TrialObservation(
        consecutive_misses=3,
        grace_observations=2,
        piece_now_on_c3=False,
        piece_in_exit_zone_now=False,
        last_seen_in_exit_zone=True,
        pulses_fired=2,
        max_pulses=10,
    )
    assert determineNextStatus(obs) == "exited"


def test_determineNextStatus_pending_when_misses_within_grace() -> None:
    obs = TrialObservation(
        consecutive_misses=2,
        grace_observations=2,
        piece_now_on_c3=False,
        piece_in_exit_zone_now=False,
        last_seen_in_exit_zone=False,
        pulses_fired=2,
        max_pulses=10,
    )
    assert determineNextStatus(obs) == "pending"


def test_determineNextStatus_no_exit_when_max_pulses_exceeded() -> None:
    obs = TrialObservation(
        consecutive_misses=0,
        grace_observations=2,
        piece_now_on_c3=False,
        piece_in_exit_zone_now=False,
        last_seen_in_exit_zone=False,
        pulses_fired=10,
        max_pulses=10,
    )
    assert determineNextStatus(obs) == "no_exit"


def test_determineNextStatus_pending_while_in_flight() -> None:
    obs = TrialObservation(
        consecutive_misses=0,
        grace_observations=2,
        piece_now_on_c3=False,
        piece_in_exit_zone_now=False,
        last_seen_in_exit_zone=False,
        pulses_fired=2,
        max_pulses=10,
    )
    assert determineNextStatus(obs) == "pending"


# ---------------------------------------------------------------------------
# Runner integration with mocks
# ---------------------------------------------------------------------------


class _FakeStepper:
    def __init__(self, name: str) -> None:
        self._name = name
        self.speed_limits: tuple[int, int] | None = None
        self.acceleration: int | None = None
        self.move_calls: list[int] = []
        self._gc = None  # set by fixture

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits = (min_speed, max_speed)

    def set_acceleration(self, acceleration: int) -> None:
        self.acceleration = acceleration

    def move_steps(self, steps: int, *, force: bool = False) -> bool:
        self.move_calls.append(int(steps))
        return True

    def degrees_for_microsteps(self, steps: int) -> float:
        return float(steps) / 100.0

    @property
    def stopped(self) -> bool:
        return True


@dataclass
class _FakeVisionScript:
    """Scripted vision behavior. Each entry is a tuple of (c2_ids, c3_ids).

    The script advances on every ``getFeederTrackerLiveGlobalIds`` call so
    tests can simulate the piece appearing on c2, then moving to c3 (or
    disappearing).
    """

    timeline: list[tuple[set[int], set[int]]] = field(default_factory=list)
    exit_zone_gids: set[int] = field(default_factory=set)
    _index: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    tracker_active_calls: list[bool] = field(default_factory=list)

    def setFeederTrackerActive(self, active: bool) -> None:
        self.tracker_active_calls.append(bool(active))

    def getFeederTrackerLiveGlobalIds(self, role: str) -> set[int]:
        with self._lock:
            if not self.timeline:
                return set()
            idx = min(self._index, len(self.timeline) - 1)
            self._index += 1
            c2, c3 = self.timeline[idx]
            return set(c2) if role == "c_channel_2" else set(c3)

    def feederTrackGidInExitZone(self, role: str, global_id: int) -> bool:
        return int(global_id) in self.exit_zone_gids


@pytest.fixture
def fast_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    # Squash all sleeps so trials run in milliseconds.
    monkeypatch.setattr(runner_mod, "WAIT_FOR_PIECE_TIMEOUT_S", 1.0)
    monkeypatch.setattr(runner_mod, "WAIT_FOR_PIECE_POLL_INTERVAL_S", 0.001)
    monkeypatch.setattr(runner_mod, "WAIT_FOR_PIECE_C1_PULSE_INTERVAL_S", 0.001)
    monkeypatch.setattr(runner_mod, "TRIAL_PULSE_BUSY_POLL_S", 0.001)
    monkeypatch.setattr(runner_mod, "TRIAL_BETWEEN_PULSE_FLOOR_S", 0.0)
    monkeypatch.setattr(runner_mod, "TRIAL_VISION_SETTLE_S", 0.001)
    monkeypatch.setattr(runner_mod, "TRIAL_MAX_PULSES", 4)


class _GcStub:
    def __init__(self) -> None:
        self.logger = logging.getLogger("c-channel-stress-test")


def _waitForRunComplete(runner: CChannelTrackingStressRunner, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while runner.isActive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not runner.isActive(), "runner did not finish in time"


def _makeRunner(vision: _FakeVisionScript) -> tuple[CChannelTrackingStressRunner, _FakeStepper, _FakeStepper]:
    c1 = _FakeStepper("c1")
    c2 = _FakeStepper("c2")
    runner = CChannelTrackingStressRunner(
        _GcStub(),  # type: ignore[arg-type]
        c1_stepper=c1,
        c2_stepper=c2,
        vision=vision,
        c1_pulse_steps=100,
        c1_speed_microsteps_per_second=1500,
        c1_acceleration_microsteps_per_second_sq=5000,
        c1_delay_between_pulse_ms=200,
        c2_default_speed_microsteps_per_second=5000,
        c2_default_acceleration_microsteps_per_second_sq=20000,
    )
    return runner, c1, c2


def test_runner_marks_no_piece_when_c2_never_observes_one(fast_runner: None) -> None:
    vision = _FakeVisionScript(timeline=[(set(), set())] * 2000)
    runner, c1, c2 = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=5000,
        speed_step=1000,
        pulse_steps=500,
    )
    runner.start(sweep)
    _waitForRunComplete(runner)
    state = runner.getState()
    assert state is not None
    assert state.status == "completed"
    assert len(state.trials) == 1
    assert state.trials[0].status == "no_piece"
    assert vision.tracker_active_calls == [True]
    # C1 was pulsed at least once while waiting for the piece.
    assert c1.move_calls
    # C2 was never asked to pulse (no piece arrived).
    assert c2.move_calls == []


def test_runner_records_delivered_when_piece_reaches_c3(fast_runner: None) -> None:
    # Sequence calls: each call returns one of these.
    # 1st pair = first c2 query (before c1 pulse) → still empty
    # 2nd pair = c2 query after baseline → piece arrived
    # subsequent = piece moves to c3 on first c2 pulse
    timeline: list[tuple[set[int], set[int]]] = [
        (set(), set()),  # baseline at trial start
        ({7}, set()),    # piece arrives
        (set(), {7}),    # after pulse: now on c3
    ] + [(set(), {7})] * 20
    vision = _FakeVisionScript(timeline=timeline)
    runner, c1, c2 = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=5000,
        speed_step=1000,
        pulse_steps=500,
    )
    runner.start(sweep)
    _waitForRunComplete(runner)
    state = runner.getState()
    assert state is not None
    trial = state.trials[0]
    assert trial.status == "delivered"
    assert trial.tracked_global_id == 7
    assert trial.pulses_fired == 1
    # c2 stress params were applied
    assert c2.speed_limits == (16, 5000)


def test_runner_records_track_lost_when_piece_disappears_mid_pulse(fast_runner: None) -> None:
    timeline: list[tuple[set[int], set[int]]] = [
        (set(), set()),     # baseline
        ({9}, set()),       # piece arrives
        (set(), set()),     # after pulse: gone from c2, not on c3 → track lost
    ] + [(set(), set())] * 20
    vision = _FakeVisionScript(timeline=timeline)
    runner, _, c2 = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=5000,
        speed_step=1000,
        pulse_steps=500,
        track_loss_grace_observations=0,
    )
    runner.start(sweep)
    _waitForRunComplete(runner)
    state = runner.getState()
    assert state is not None
    trial = state.trials[0]
    assert trial.status == "track_lost"
    assert trial.tracked_global_id == 9
    assert trial.pulses_fired == 1


def test_runner_records_exited_when_piece_vanishes_from_exit_zone(fast_runner: None) -> None:
    # Piece arrives, is seen in the exit zone, then disappears — a clean
    # exit (it fell off the end), not a track loss.
    timeline: list[tuple[set[int], set[int]]] = [
        (set(), set()),  # baseline
        ({5}, set()),    # piece arrives → detected by wait-for-piece
        ({5}, set()),    # pulse 1 obs: still on c2 (records exit-zone sighting)
        (set(), set()),  # pulse 1 c3 read
        (set(), set()),  # pulse 2 obs: gone from c2 → exited (was in exit zone)
    ] + [(set(), set())] * 20
    vision = _FakeVisionScript(timeline=timeline, exit_zone_gids={5})
    runner, _, _ = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=5000,
        speed_step=1000,
        pulse_steps=500,
        track_loss_grace_observations=0,
    )
    runner.start(sweep)
    _waitForRunComplete(runner)
    state = runner.getState()
    assert state is not None
    trial = state.trials[0]
    assert trial.status == "exited"
    assert trial.tracked_global_id == 5


def test_runner_records_no_exit_when_piece_never_leaves_c2(fast_runner: None) -> None:
    # Piece arrives once and then stays on c2 forever — pulses keep firing
    # until max_pulses (4 from fast_runner) is hit.
    timeline: list[tuple[set[int], set[int]]] = [
        (set(), set()),  # baseline
    ] + [({3}, set())] * 50
    vision = _FakeVisionScript(timeline=timeline)
    runner, _, c2 = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=5000,
        speed_step=1000,
        pulse_steps=500,
    )
    runner.start(sweep)
    _waitForRunComplete(runner)
    state = runner.getState()
    assert state is not None
    trial = state.trials[0]
    assert trial.status == "no_exit"
    assert trial.pulses_fired == runner_mod.TRIAL_MAX_PULSES


def test_runner_continues_sweep_after_track_lost(fast_runner: None) -> None:
    # Losing a track is expected during a sweep — the run must record it and
    # keep going through every remaining trial rather than bricking.
    timeline: list[tuple[set[int], set[int]]] = [
        (set(), set()),  # trial 1 baseline
        ({9}, set()),    # piece arrives
        (set(), set()),  # gone mid-channel → track_lost
    ] + [(set(), set())] * 5000  # trial 2 then finds no piece and times out
    vision = _FakeVisionScript(timeline=timeline)
    runner, _, _ = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=2500,
        speed_step=2500,
        pulse_steps=500,
        track_loss_grace_observations=0,
    )
    runner.start(sweep)
    _waitForRunComplete(runner, timeout_s=5.0)
    state = runner.getState()
    assert state is not None
    assert state.status == "completed"
    assert len(state.trials) == 2
    assert state.trials[0].status == "track_lost"
    # The second trial still ran (it didn't brick after the loss).
    assert state.trials[1].status in {"no_piece", "track_lost", "exited", "delivered", "no_exit"}


def test_runner_stop_aborts_loop(fast_runner: None) -> None:
    # Provide enough timeline entries that the runner would happily keep
    # going through multiple trials — we want stop() to terminate it
    # cleanly before completion.
    timeline: list[tuple[set[int], set[int]]] = [
        (set(), set()),
    ] + [({1}, set())] * 5000
    vision = _FakeVisionScript(timeline=timeline)
    runner, _, _ = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=2000,
        speed_step=500,
        pulse_steps=500,
    )
    runner.start(sweep)
    # Allow the runner to take its first step then issue stop.
    time.sleep(0.02)
    runner.stop()
    _waitForRunComplete(runner, timeout_s=2.0)
    state = runner.getState()
    assert state is not None
    assert state.status == "stopped"


def test_runner_rejects_concurrent_start(fast_runner: None) -> None:
    timeline = [(set(), set())] * 50
    vision = _FakeVisionScript(timeline=timeline)
    runner, _, _ = _makeRunner(vision)
    sweep = StressSweepConfig(
        top_speed=5000,
        min_speed=5000,
        speed_step=1000,
        pulse_steps=500,
    )
    runner.start(sweep)
    with pytest.raises(RuntimeError):
        runner.start(sweep)
    runner.stop()
    _waitForRunComplete(runner)
