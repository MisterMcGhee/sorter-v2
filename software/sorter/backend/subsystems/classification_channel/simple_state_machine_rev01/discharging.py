import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Discharging(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._kickoff_started = False
        self._stepper_done_at: Optional[float] = None

    def step(self) -> Optional[ClassificationChannelState]:
        self.setClassificationReady(False, "discharging")

        if not self._kickoff_started:
            self.ctx.discharging_started_at = time.monotonic()
            cfg = self.ctx.config
            output_deg = self._planDischargeOutputDeg()
            if not self.startOutputMove(
                output_deg,
                cfg.discharge_speed_usteps_per_s,
            ):
                self.logger.error(
                    f"{LOG_TAG} could not start discharge move — abort to IDLE"
                )
                return ClassificationChannelState.IDLE
            self._kickoff_started = True
            self.logger.info(
                f"{LOG_TAG} DISCHARGING move-to-exit started "
                f"(output={output_deg:.1f}°, "
                f"speed={cfg.discharge_speed_usteps_per_s} µsteps/s)"
            )

        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is not None and not bool(stepper.stopped):
            return None

        if self._stepper_done_at is None:
            self._stepper_done_at = time.monotonic()

        pause_s = self.ctx.config.post_discharge_pause_ms / 1000.0
        if time.monotonic() - self._stepper_done_at < pause_s:
            return None

        elapsed = time.monotonic() - self.ctx.discharging_started_at
        self.logger.info(
            f"{LOG_TAG} DISCHARGING -> VERIFYING_DISCHARGE (move complete after {elapsed:.2f}s)"
        )
        return ClassificationChannelState.REV01_VERIFYING_DISCHARGE

    def _planDischargeOutputDeg(self) -> float:
        fallback = max(2.0, 2.0 * float(self.cc_config.drop_tolerance_deg))
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is not None:
            raw = perception_service.read_bboxes_and_frame(4)
            bboxes = [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in raw[0]] if raw else []
            center = perception_service.channel_center(4)
        else:
            bboxes = self.cv.bboxesOnChannel()
            center = self.cv.channelCenter()
        primary = self.cv.primaryBbox(bboxes)
        if primary is None:
            self.logger.warning(
                f"{LOG_TAG} discharge: no bbox visible — falling back to fixed "
                f"{fallback:.1f}° forward move"
            )
            return fallback
        if center is None:
            self.logger.warning(
                f"{LOG_TAG} discharge: no carousel center geometry — falling back to "
                f"{fallback:.1f}°"
            )
            return fallback
        piece_angle = self.cv.bboxAngleDeg(primary, center)
        target_angle = (
            float(self.cc_config.drop_angle_deg) + float(self.cc_config.drop_tolerance_deg)
        ) % 360.0
        delta = (target_angle - piece_angle) % 360.0
        return max(2.0, min(delta, 270.0))

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._kickoff_started = False
        self._stepper_done_at = None
