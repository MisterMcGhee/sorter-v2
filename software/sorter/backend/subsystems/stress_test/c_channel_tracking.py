"""C-channel tracking stress-test runner.

Background-thread driver. Pulses C1 (using its current production config) to
dispense one piece at a time, then pulses C2 at the trial's stress params
while polling the live feeder tracker to decide whether the piece survived
the transit to C3 or got lost mid-pulse.

The runner reuses the same stepper API, ``RotorPulseConfig`` shape, and
feeder tracker the main feeder uses. The only thing it owns is the
``set_speed_limits`` / ``set_acceleration`` override for C2 while the trial
runs (restored on exit).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from global_config import GlobalConfig
from subsystems.stress_test.algorithm import (
    StressSweepConfig,
    StressTrialParams,
    StressTrialResult,
    StressTrialStatus,
    TrialObservation,
    buildLinearSweep,
    determineNextStatus,
)


StressRunStatus = Literal[
    "running",
    "waiting_for_piece",
    "paused",
    "stopping",
    "completed",
    "stopped",
    "failed",
]


# Tunables. Kept module-level so unit tests can monkey-patch.
WAIT_FOR_PIECE_TIMEOUT_S: float = 30.0
WAIT_FOR_PIECE_POLL_INTERVAL_S: float = 0.05
WAIT_FOR_PIECE_C1_PULSE_INTERVAL_S: float = 1.0
TRIAL_PULSE_BUSY_POLL_S: float = 0.01
TRIAL_BETWEEN_PULSE_FLOOR_S: float = 0.001
TRIAL_MAX_PULSES: int = 12
TRIAL_VISION_SETTLE_S: float = 0.15
# Interval between successive tracker reads inside a single pulse window.
# Each read counts as one "observation" against the grace counter.
TRIAL_OBSERVATION_INTERVAL_S: float = 0.05


class _StepperLike(Protocol):
    _name: str

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None: ...
    def set_acceleration(self, acceleration: int) -> None: ...
    def move_steps(self, steps: int, *, force: bool = ...) -> bool: ...
    def degrees_for_microsteps(self, steps: int) -> float: ...
    @property
    def stopped(self) -> bool: ...


class _VisionLike(Protocol):
    def setFeederTrackerActive(self, active: bool) -> None: ...
    def getFeederTrackerLiveGlobalIds(self, role: str) -> set[int]: ...
    def feederTrackGidInExitZone(self, role: str, global_id: int) -> bool: ...


@dataclass
class StressTestState:
    run_id: str
    sweep: StressSweepConfig
    started_at: float
    status: StressRunStatus = "running"
    trials: list[StressTrialResult] = field(default_factory=list)
    current_trial_index: int | None = None
    ended_at: float | None = None
    error: str | None = None
    last_event: str | None = None

    def toDict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "current_trial_index": self.current_trial_index,
            "last_event": self.last_event,
            "error": self.error,
            "sweep": {
                "top_speed": self.sweep.top_speed,
                "min_speed": self.sweep.min_speed,
                "speed_step": self.sweep.speed_step,
                "pulse_steps": self.sweep.pulse_steps,
                "start_pause_ms": self.sweep.start_pause_ms,
                "max_pause_ms": self.sweep.max_pause_ms,
                "pause_step_ms": self.sweep.pause_step_ms,
                "acceleration_microsteps_per_second_sq": (
                    self.sweep.acceleration_microsteps_per_second_sq
                ),
                "track_loss_grace_observations": (
                    self.sweep.track_loss_grace_observations
                ),
            },
            "trials": [trial.toDict() for trial in self.trials],
        }


def _snapshot(state: StressTestState) -> StressTestState:
    return StressTestState(
        run_id=state.run_id,
        sweep=state.sweep,
        started_at=state.started_at,
        status=state.status,
        trials=[
            StressTrialResult(
                params=trial.params,
                status=trial.status,
                tracked_global_id=trial.tracked_global_id,
                pulses_fired=trial.pulses_fired,
                duration_s=trial.duration_s,
                note=trial.note,
            )
            for trial in state.trials
        ],
        current_trial_index=state.current_trial_index,
        ended_at=state.ended_at,
        error=state.error,
        last_event=state.last_event,
    )


class CChannelTrackingStressRunner:
    """Owns the background loop and the c2 stepper-speed override window."""

    def __init__(
        self,
        gc: GlobalConfig,
        *,
        c1_stepper: _StepperLike,
        c2_stepper: _StepperLike,
        vision: _VisionLike,
        c1_pulse_steps: int,
        c1_speed_microsteps_per_second: int,
        c1_acceleration_microsteps_per_second_sq: int,
        c1_delay_between_pulse_ms: int,
        c2_default_speed_microsteps_per_second: int,
        c2_default_acceleration_microsteps_per_second_sq: int,
    ) -> None:
        self.gc = gc
        self.logger = gc.logger
        self._c1 = c1_stepper
        self._c2 = c2_stepper
        self._vision = vision
        self._c1_pulse_steps = int(c1_pulse_steps)
        self._c1_speed = int(c1_speed_microsteps_per_second)
        self._c1_accel = int(c1_acceleration_microsteps_per_second_sq)
        self._c1_delay_ms = int(c1_delay_between_pulse_ms)
        self._c2_default_speed = int(c2_default_speed_microsteps_per_second)
        self._c2_default_accel = int(c2_default_acceleration_microsteps_per_second_sq)

        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._state: StressTestState | None = None

    # -- public API --------------------------------------------------------

    def isActive(self) -> bool:
        with self._lock:
            t = self._thread
            return bool(t is not None and t.is_alive())

    def getState(self) -> StressTestState | None:
        with self._lock:
            return _snapshot(self._state) if self._state is not None else None

    def start(self, sweep: StressSweepConfig) -> StressTestState:
        with self._lock:
            if self.isActive():
                raise RuntimeError("A C-channel tracking stress test is already running")
            trials = [
                StressTrialResult(params=params) for params in buildLinearSweep(sweep)
            ]
            if not trials:
                raise ValueError("sweep produced no trials")
            now = time.time()
            self._state = StressTestState(
                run_id=str(uuid.uuid4()),
                sweep=sweep,
                started_at=now,
                trials=trials,
                status="running",
                current_trial_index=0,
                last_event="started",
            )
            self._stop_event.clear()
            self._pause_event.set()
            self._thread = threading.Thread(
                target=self._run, name="CChannelTrackingStress", daemon=True
            )
            self._thread.start()
            return _snapshot(self._state)

    def pause(self) -> None:
        with self._lock:
            if not self.isActive() or self._state is None:
                raise RuntimeError("No stress test is running")
            if self._state.status in ("paused", "stopping"):
                return
            self._pause_event.clear()
            self._state.status = "paused"
            self._state.last_event = "paused"
        self.logger.info("C-channel stress: pause requested")

    def resume(self) -> None:
        with self._lock:
            if not self.isActive() or self._state is None:
                raise RuntimeError("No stress test is running")
            if self._state.status != "paused":
                return
            self._state.status = "running"
            self._state.last_event = "resumed"
            self._pause_event.set()
        self.logger.info("C-channel stress: resumed")

    def stop(self) -> None:
        with self._lock:
            if self._state is None:
                raise RuntimeError("No stress test is running")
            self._stop_event.set()
            self._pause_event.set()
            if self._state.status not in ("completed", "stopped", "failed"):
                self._state.status = "stopping"
                self._state.last_event = "stop_requested"
        self.logger.info("C-channel stress: stop requested")

    # -- internal helpers --------------------------------------------------

    def _setEvent(self, event: str) -> None:
        with self._lock:
            if self._state is not None:
                self._state.last_event = event

    def _setStatus(self, status: StressRunStatus) -> None:
        with self._lock:
            if self._state is not None:
                self._state.status = status

    def _isPaused(self) -> bool:
        return not self._pause_event.is_set()

    def _pulseC1Once(self) -> bool:
        try:
            self._c1.set_speed_limits(min_speed=16, max_speed=self._c1_speed)
            self._c1.set_acceleration(self._c1_accel)
        except Exception as exc:
            self.logger.warning(f"C1 set_speed/accel failed: {exc}")
        success = bool(self._c1.move_steps(int(self._c1_pulse_steps)))
        if not success:
            return False
        self._waitForStop(self._c1, timeout_s=5.0)
        return True

    def _waitForStop(self, stepper: _StepperLike, timeout_s: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return False
            try:
                if stepper.stopped:
                    return True
            except Exception:
                return False
            time.sleep(TRIAL_PULSE_BUSY_POLL_S)
        return False

    def _waitForPieceOnC2(self, baseline_ids: set[int]) -> int | None:
        """Pulse C1 slowly until a *new* global_id appears on the C2 tracker.

        Returns the newly observed global_id, or ``None`` on timeout / stop /
        pause.
        """
        self._setEvent("waiting_for_piece")
        self._setStatus("waiting_for_piece")
        deadline = time.monotonic() + WAIT_FOR_PIECE_TIMEOUT_S
        next_c1_pulse_at = 0.0
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return None
            if self._isPaused():
                return None
            live = self._vision.getFeederTrackerLiveGlobalIds("c_channel_2")
            new_ids = live - baseline_ids
            if new_ids:
                self._setStatus("running")
                self._setEvent("piece_detected_on_c2")
                return int(sorted(new_ids)[0])
            now = time.monotonic()
            if now >= next_c1_pulse_at:
                self._pulseC1Once()
                next_c1_pulse_at = now + WAIT_FOR_PIECE_C1_PULSE_INTERVAL_S
            time.sleep(WAIT_FOR_PIECE_POLL_INTERVAL_S)
        return None

    def _applyTrialParamsToC2(self, params: StressTrialParams) -> None:
        self._c2.set_speed_limits(min_speed=16, max_speed=params.speed_microsteps_per_second)
        self._c2.set_acceleration(int(params.acceleration_microsteps_per_second_sq))

    def _restoreC2Defaults(self) -> None:
        try:
            self._c2.set_speed_limits(min_speed=16, max_speed=self._c2_default_speed)
            self._c2.set_acceleration(self._c2_default_accel)
        except Exception as exc:
            self.logger.warning(f"C2 restore defaults failed: {exc}")

    def _runOneTrial(self, trial: StressTrialResult) -> None:
        trial_started = time.monotonic()
        baseline_c2 = self._vision.getFeederTrackerLiveGlobalIds("c_channel_2")
        gid = self._waitForPieceOnC2(baseline_c2)
        if gid is None:
            if self._stop_event.is_set() or self._isPaused():
                trial.status = "skipped"
                trial.note = "stopped or paused"
            else:
                trial.status = "no_piece"
                trial.note = "timed out waiting for piece on c2"
            trial.duration_s = time.monotonic() - trial_started
            return

        trial.tracked_global_id = gid
        self._applyTrialParamsToC2(trial.params)

        pause_s = max(TRIAL_BETWEEN_PULSE_FLOOR_S, trial.params.pause_ms / 1000.0)
        pulse_steps = int(trial.params.pulse_steps)
        max_pulses = TRIAL_MAX_PULSES
        grace = int(self._state.sweep.track_loss_grace_observations) if self._state else 0
        consecutive_misses = 0
        last_seen_in_exit_zone = False

        for pulse_idx in range(1, max_pulses + 1):
            if self._stop_event.is_set():
                trial.status = "skipped"
                trial.note = "stopped"
                break
            if self._isPaused():
                trial.status = "skipped"
                trial.note = "paused mid-trial"
                break
            if not self._c2.move_steps(pulse_steps):
                trial.note = "move_steps rejected"
                trial.status = "skipped"
                break
            self._waitForStop(self._c2, timeout_s=5.0)
            trial.pulses_fired = pulse_idx
            # Let the vision thread tick at least once after motion stops so
            # the tracker has a chance to either confirm c2 presence or hand
            # the piece off to c3 before we decide.
            time.sleep(TRIAL_VISION_SETTLE_S)

            # Poll the tracker repeatedly across the post-pulse settle and
            # the pause window. Each read is one observation against the
            # grace counter — the piece is allowed to vanish for up to
            # ``grace`` consecutive reads before we declare track_lost. A
            # successful re-sighting resets the counter.
            observe_until = time.monotonic() + pause_s
            terminal_status: StressTrialStatus | None = None
            while True:
                c2_ids = self._vision.getFeederTrackerLiveGlobalIds("c_channel_2")
                c3_ids = self._vision.getFeederTrackerLiveGlobalIds("c_channel_3")
                # Is the piece in the exit zone right now? This is checked
                # against the cached tracks (which include coasting tracks),
                # so it can be True even when the piece has dropped out of the
                # live-id set. Reaching the exit zone == made it.
                try:
                    in_exit_now = self._vision.feederTrackGidInExitZone("c_channel_2", gid)
                except Exception:
                    in_exit_now = False
                if in_exit_now:
                    last_seen_in_exit_zone = True
                if gid in c2_ids:
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
                obs = TrialObservation(
                    consecutive_misses=consecutive_misses,
                    grace_observations=grace,
                    piece_now_on_c3=gid in c3_ids,
                    piece_in_exit_zone_now=in_exit_now,
                    last_seen_in_exit_zone=last_seen_in_exit_zone,
                    pulses_fired=pulse_idx,
                    max_pulses=max_pulses,
                )
                status = determineNextStatus(obs)
                if status != "pending":
                    terminal_status = status
                    break
                if time.monotonic() >= observe_until:
                    break
                if self._stop_event.is_set() or self._isPaused():
                    break
                time.sleep(TRIAL_OBSERVATION_INTERVAL_S)

            if terminal_status is not None:
                trial.status = terminal_status
                if terminal_status == "track_lost":
                    trial.note = (
                        f"vanished mid-channel after {consecutive_misses} "
                        f"missed observations (too fast)"
                    )
                elif terminal_status == "exited":
                    trial.note = "fell off exit zone — clean exit"
                break

        if trial.status == "pending":
            trial.status = "no_exit"
            trial.note = f"still on c2 after {max_pulses} pulses (too gentle)"
        trial.duration_s = time.monotonic() - trial_started

    def _run(self) -> None:
        assert self._state is not None
        prev_speed = self._c2_default_speed
        prev_accel = self._c2_default_accel
        self._vision.setFeederTrackerActive(True)
        try:
            while True:
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                with self._lock:
                    idx = self._state.current_trial_index or 0
                    if idx >= len(self._state.trials):
                        break
                    trial = self._state.trials[idx]
                    self._state.last_event = f"trial_{idx}_start"

                self.logger.info(
                    f"C-channel stress trial {idx + 1}/{len(self._state.trials)}: "
                    f"speed={trial.params.speed_microsteps_per_second} "
                    f"pulse_steps={trial.params.pulse_steps} "
                    f"pause_ms={trial.params.pause_ms}"
                )
                self._runOneTrial(trial)
                self.logger.info(
                    f"C-channel stress trial {idx + 1} → {trial.status} "
                    f"(pulses={trial.pulses_fired}, dur={trial.duration_s:.2f}s)"
                )

                with self._lock:
                    self._state.last_event = f"trial_{idx}_{trial.status}"
                    self._state.current_trial_index = idx + 1

            final_status: StressRunStatus = (
                "stopped" if self._stop_event.is_set() else "completed"
            )
            with self._lock:
                self._state.status = final_status
                self._state.ended_at = time.time()
                self._state.last_event = final_status
        except Exception as exc:
            self.logger.error(f"C-channel tracking stress failed: {exc}", exc_info=True)
            with self._lock:
                if self._state is not None:
                    self._state.status = "failed"
                    self._state.error = str(exc)
                    self._state.ended_at = time.time()
                    self._state.last_event = "failed"
        finally:
            self._restoreC2Defaults()
            # Leave the feeder tracker on — toggling it off would purge the
            # main machine's piece state if the operator pivots back to a
            # sorting run. The next "standby" transition in SorterController
            # will reset it normally.
            _ = prev_speed
            _ = prev_accel


# ---------------------------------------------------------------------------
# Singleton accessor — mirrors the chute_stress runner pattern so the router
# can grab the active runner without re-resolving hardware on every call.
# ---------------------------------------------------------------------------

_runner_lock = threading.Lock()
_runner: CChannelTrackingStressRunner | None = None


def getCChannelTrackingRunner(
    gc: GlobalConfig,
    *,
    c1_stepper: _StepperLike,
    c2_stepper: _StepperLike,
    vision: _VisionLike,
    c1_pulse_steps: int,
    c1_speed_microsteps_per_second: int,
    c1_acceleration_microsteps_per_second_sq: int,
    c1_delay_between_pulse_ms: int,
    c2_default_speed_microsteps_per_second: int,
    c2_default_acceleration_microsteps_per_second_sq: int,
) -> CChannelTrackingStressRunner:
    """Return the singleton runner, rebuilding it if hardware refs changed."""
    global _runner
    with _runner_lock:
        needs_new = (
            _runner is None
            or _runner._c1 is not c1_stepper
            or _runner._c2 is not c2_stepper
            or _runner._vision is not vision
        )
        if needs_new:
            if _runner is not None and _runner.isActive():
                raise RuntimeError(
                    "A stress test is running against a different hardware instance"
                )
            _runner = CChannelTrackingStressRunner(
                gc,
                c1_stepper=c1_stepper,
                c2_stepper=c2_stepper,
                vision=vision,
                c1_pulse_steps=c1_pulse_steps,
                c1_speed_microsteps_per_second=c1_speed_microsteps_per_second,
                c1_acceleration_microsteps_per_second_sq=c1_acceleration_microsteps_per_second_sq,
                c1_delay_between_pulse_ms=c1_delay_between_pulse_ms,
                c2_default_speed_microsteps_per_second=c2_default_speed_microsteps_per_second,
                c2_default_acceleration_microsteps_per_second_sq=c2_default_acceleration_microsteps_per_second_sq,
            )
        assert _runner is not None
        return _runner


def getActiveCChannelTrackingRunner() -> CChannelTrackingStressRunner | None:
    with _runner_lock:
        return _runner
