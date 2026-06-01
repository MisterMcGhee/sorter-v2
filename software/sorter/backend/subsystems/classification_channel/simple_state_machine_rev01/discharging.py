import time
from enum import Enum
from typing import Optional

from subsystems.classification_channel.incidents import (
    clear_classification_exit_stuck_incident,
    publish_classification_exit_stuck_incident,
)
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.common.jitter_recovery import JitterParams, JitterPhase, JitterSequence

from .base import Rev01BaseState
from .constants import LOG_TAG


class _Phase(str, Enum):
    CONVERGE = "converge"
    SETTLE = "settle"
    JITTER = "jitter"
    STUCK = "stuck"


class Discharging(Rev01BaseState):
    """Closed-loop discharge (active perception path).

    Drive the leading on-channel piece's center-of-mass onto the CENTER of the
    fall-off (exit-only) zone with repeated bounded moves, re-reading perception
    after each, until it is within tolerance or the converge time budget runs
    out. Then settle and re-check whether it fell. If it didn't, run the jitter
    sequence; if jitter is exhausted, raise an operator exit-stuck incident and
    hold (channel gate stays not-ready) until perception sees the channel
    physically cleared, then auto-resume.

    The loop repeats until EVERY piece is off the channel, so a multi-feed (two
    pieces sharing one cycle) clears both — the trailing piece included.

    On the non-perception fallback path there is no per-piece COM signal, so it
    degrades to the legacy single fixed kick-off move and returns to IDLE.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._phase = _Phase.CONVERGE
        self._converge_started_at: Optional[float] = None
        self._settle_started_at: Optional[float] = None
        self._released = False
        self._incident_raised = False
        self._seq: Optional[JitterSequence] = None
        # legacy fallback only
        self._kick_started = False
        self._kick_done_at: Optional[float] = None

    def step(self) -> Optional[ClassificationChannelState]:
        self.setClassificationReady(False, "discharging")
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return self._step_legacy_fallback()
        return self._step_perception(perception_service)

    # ---- active perception path ----

    def _step_perception(self, perception_service) -> Optional[ClassificationChannelState]:
        now = time.monotonic()
        cfg = self.ctx.config
        state = perception_service.read_state(4)
        n = int(state.n_pieces)
        in_exit = bool(state.in_exit)

        if n >= 2 and not self.ctx.multi_feed_detected:
            self.ctx.multi_feed_detected = True

        stepper = getattr(self.irl, "carousel_stepper", None)
        moving = stepper is not None and not bool(stepper.stopped)

        # Channel fully clear → every piece is off. Commit the tracked piece to
        # distribution if we haven't already, clear any exit-stuck incident, done.
        if n == 0 and not moving:
            self._releaseOnce()
            if self._incident_raised:
                clear_classification_exit_stuck_incident(self.gc)
                self._incident_raised = False
                self.logger.info(f"{LOG_TAG} DISCHARGING: channel cleared — resuming")
            self.logger.info(f"{LOG_TAG} DISCHARGING -> IDLE (channel clear)")
            return ClassificationChannelState.IDLE

        # Discrete positioning moves must finish before we re-read and re-issue.
        # Jitter manages its own timing via is_jittering(), so it is exempt.
        if self._phase in (_Phase.CONVERGE, _Phase.SETTLE) and moving:
            return None

        if self._phase == _Phase.CONVERGE:
            return self._converge(state, cfg, now)
        if self._phase == _Phase.SETTLE:
            return self._settle(cfg, now, in_exit)
        if self._phase == _Phase.JITTER:
            return self._jitter(cfg, now, in_exit)
        if self._phase == _Phase.STUCK:
            return self._stuck(now, in_exit)
        return None

    def _converge(self, state, cfg, now: float) -> Optional[ClassificationChannelState]:
        if self._converge_started_at is None:
            self._converge_started_at = now

        gap = state.exit_com_forward_to_center_deg
        if gap is None:
            # No center signal but pieces present — fall back to the leading-edge
            # gap so we still advance toward the exit.
            gap = state.exit_com_forward_deg
        if gap is None:
            gap = min(float(cfg.discharge_max_move_output_deg), 30.0)

        elapsed_ms = (now - self._converge_started_at) * 1000.0
        if abs(gap) <= float(cfg.discharge_center_tolerance_deg):
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: piece at fall-off center (gap={gap:.1f}°) — settling"
            )
            self._enterSettle(now)
            return None
        if elapsed_ms >= float(cfg.discharge_converge_timeout_ms):
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: converge budget "
                f"{cfg.discharge_converge_timeout_ms}ms spent (gap={gap:.1f}°) — "
                f"settling, jitter if still stuck"
            )
            self._enterSettle(now)
            return None

        # Only ever drive forward; a piece slightly past center is already in the
        # fall-off zone and gets handled by settle/jitter.
        move = min(max(0.0, gap), float(cfg.discharge_max_move_output_deg))
        if move <= 0.0:
            self._enterSettle(now)
            return None
        self.startOutputMove(move, cfg.discharge_speed_usteps_per_s)
        return None

    def _enterSettle(self, now: float) -> None:
        # Reaching the fall-off zone is the analogue of the old "kick complete":
        # release the piece to distribution so it commits/records.
        self._releaseOnce()
        self._phase = _Phase.SETTLE
        self._settle_started_at = now

    def _settle(self, cfg, now: float, in_exit: bool) -> Optional[ClassificationChannelState]:
        if self._settle_started_at is None:
            self._settle_started_at = now
        if (now - self._settle_started_at) * 1000.0 < float(cfg.discharge_settle_ms):
            return None
        if not in_exit:
            # Fell cleanly. If pieces remain (multi-feed), converge the next one.
            self._restartConverge()
            return None
        self.logger.info(
            f"{LOG_TAG} DISCHARGING: parked at center but still in exit — jitter recovery"
        )
        self._phase = _Phase.JITTER
        return self._jitter(cfg, now, in_exit)

    def _jitter(self, cfg, now: float, in_exit: bool) -> Optional[ClassificationChannelState]:
        seq = self._getOrBuildSeq(cfg)
        if seq is None:
            self.logger.warning(
                f"{LOG_TAG} DISCHARGING: jitter unavailable — raising exit-stuck incident"
            )
            self._raiseStuck(now)
            return None
        if not seq.is_active:
            seq.start()
        phase = seq.tick(still_stuck=in_exit, now=now)
        if phase == JitterPhase.CLEARED:
            self.logger.info(f"{LOG_TAG} DISCHARGING: jitter cleared the piece")
            self._restartConverge()
            return None
        if phase == JitterPhase.EXHAUSTED:
            self._raiseStuck(now)
            return None
        return None

    def _stuck(self, now: float, in_exit: bool) -> Optional[ClassificationChannelState]:
        # Hold until the operator physically clears the piece. Full-clear (n == 0)
        # is handled in _step_perception. If the piece merely left the exit band
        # but the channel is not yet clear, retry the converge loop for the rest.
        if not in_exit:
            clear_classification_exit_stuck_incident(self.gc)
            self._incident_raised = False
            self._restartConverge()
        return None

    def _raiseStuck(self, now: float) -> None:
        converge_ms = 0.0
        if self._converge_started_at is not None:
            converge_ms = (now - self._converge_started_at) * 1000.0
        attempts = self._seq.attempts_made if self._seq is not None else 0
        self.logger.error(
            f"{LOG_TAG} DISCHARGING: piece stuck at fall-off center after "
            f"{attempts} jitter attempt(s) — raising exit-stuck incident, holding"
        )
        publish_classification_exit_stuck_incident(
            self.gc,
            piece=self.ctx.known_object,
            jitter_attempts=int(attempts),
            converge_ms=float(converge_ms),
        )
        self._incident_raised = True
        self._phase = _Phase.STUCK

    def _restartConverge(self) -> None:
        if self._seq is not None:
            self._seq.reset()
        self._phase = _Phase.CONVERGE
        self._converge_started_at = None
        self._settle_started_at = None

    def _releaseOnce(self) -> None:
        if self._released:
            return
        obj = self.ctx.known_object
        # advanceTransport (non-dynamic) shifts wait -> exit so the piece
        # distribution positioned for now occupies the drop slot it reads from.
        self.transport.advanceTransport()
        self.shared.set_distribution_gate(False, reason="rev01_discharged")
        self._released = True
        if obj is not None:
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: released piece {obj.uuid[:8]} to distribution"
            )

    def _getOrBuildSeq(self, cfg) -> Optional[JitterSequence]:
        if self._seq is not None:
            return self._seq
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            return None
        self._seq = JitterSequence(
            stepper,
            JitterParams(
                amplitude_motor_deg=cfg.jitter_amplitude_motor_deg,
                cycles=int(cfg.jitter_cycles),
                speed_usteps_per_s=int(cfg.jitter_speed_usteps_per_s),
                accel_usteps_per_s2=int(cfg.jitter_accel_usteps_per_s2),
                pause_ms=int(cfg.jitter_pause_ms),
                max_attempts=int(cfg.verify_discharge_max_jitter_attempts),
            ),
            label=f"{LOG_TAG} discharge",
            logger=self.logger,
        )
        return self._seq

    # ---- legacy (non-perception) fallback ----

    def _step_legacy_fallback(self) -> Optional[ClassificationChannelState]:
        cfg = self.ctx.config
        if not self._kick_started:
            self.ctx.discharging_started_at = time.monotonic()
            output_deg = float(cfg.kick_off_output_deg)
            if not self.startOutputMove(output_deg, cfg.discharge_speed_usteps_per_s):
                self.logger.error(f"{LOG_TAG} could not start discharge move — abort to IDLE")
                return ClassificationChannelState.IDLE
            self._kick_started = True
            self.logger.info(
                f"{LOG_TAG} DISCHARGING (legacy) fixed kick (output={output_deg:.1f}°)"
            )

        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is not None and not bool(stepper.stopped):
            return None

        if self._kick_done_at is None:
            self._kick_done_at = time.monotonic()
            self._releaseOnce()

        if time.monotonic() - self._kick_done_at < cfg.post_discharge_pause_ms / 1000.0:
            return None
        return ClassificationChannelState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        if self._seq is not None:
            self._seq.reset()
        self._phase = _Phase.CONVERGE
        self._converge_started_at = None
        self._settle_started_at = None
        self._released = False
        self._incident_raised = False
        self._kick_started = False
        self._kick_done_at = None
