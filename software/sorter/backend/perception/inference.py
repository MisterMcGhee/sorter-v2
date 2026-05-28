"""Per-channel inference worker — one thread per camera.

The worker is constructed with direct, immutable references to:
- its ``CaptureWorker`` (one camera, one source_id),
- its ``InferenceRuntime`` (one RKNN runtime pinned to one NPU core),
- its ``ChannelDef`` (one set of arcs, one polygon mask),
- its ``LatestStateSlot`` (its write target).

Nothing on the hot path looks anything up by role string. Cross-camera or
cross-core mixups require explicitly swapping a worker's attributes,
which the code never does — and the source_id assertion in the loop
catches that anyway.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from .arcs import attributeBboxes, forwardClearanceToExitDeg
from .capture import CaptureWorker, PerceptionFrame
from .channel import ChannelDef
from .runtime import InferenceRuntime
from .state import ChannelState, LatestStateSlot


# Callable signature for the optional KnownObject emit hook (rising edge of
# C3 → C4 hand-off). The PerceptionService wires this when the C3 worker
# is constructed; other workers leave it as ``None``.
OnExitEdge = Callable[[float], None]


# Default loop pacing constants. The capture thread runs at the camera's
# native fps (~30 Hz); these just keep us from spinning when frames are
# stale or the capture has none yet.
_IDLE_SLEEP_S = 0.005
_NO_FRAME_SLEEP_S = 0.010


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _observe(
    runtime_stats: Optional[Any], key: str, ms: float
) -> None:
    if runtime_stats is None:
        return
    fn = getattr(runtime_stats, "observePerfMs", None)
    if fn is None:
        return
    try:
        fn(key, ms)
    except Exception:
        pass


def _hit(counter: Optional[Any], key: str) -> None:
    if counter is None:
        return
    fn = getattr(counter, "hit", None)
    if fn is None:
        return
    try:
        fn(key)
    except Exception:
        pass


class InferenceWorker:
    """One thread per channel. Capture → infer → attribute → slot.write."""

    def __init__(
        self,
        *,
        capture: CaptureWorker,
        runtime: InferenceRuntime,
        channel_def: ChannelDef,
        slot: LatestStateSlot,
        conf_threshold: Optional[float] = None,
        on_exit_edge: Optional[OnExitEdge] = None,
        runtime_stats: Optional[Any] = None,
        profiler: Optional[Any] = None,
        logger: Optional[Any] = None,
    ) -> None:
        # Construction-time invariant: the capture's source_id must match
        # the channel's. After this point the worker holds direct refs;
        # nobody mutates these.
        if capture.source_id != channel_def.camera_source_id:
            raise ValueError(
                f"capture.source_id={capture.source_id!r} does not match "
                f"channel_def.camera_source_id={channel_def.camera_source_id!r} "
                f"(channel_id={channel_def.channel_id})"
            )
        self._capture = capture
        self._runtime = runtime
        self._channel_def = channel_def
        self._slot = slot
        self._conf_threshold = conf_threshold
        self._on_exit_edge = on_exit_edge
        self._runtime_stats = runtime_stats
        self._profiler = profiler
        self._logger = logger

        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name=f"perception-{channel_def.camera_source_id}",
        )
        self._last_frame_ts: float = -1.0
        self._was_in_exit: bool = False

        # Latest raw inference result — GIL-atomic tuple ref, same pattern as
        # LatestStateSlot. Written after every successful inference so the
        # classification channel state machine can read bboxes + the exact
        # frame they were computed against without triggering a new inference.
        self._latest_raw: Optional[tuple] = None

        # Public counters — read by the smoke test.
        self.iterations: int = 0
        self.inferences: int = 0
        self.source_id_assertions: int = 0   # hard fails; must stay 0
        self.errors: int = 0

    # --- lifecycle -------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def channel_id(self) -> int:
        return self._channel_def.channel_id

    @property
    def source_id(self) -> str:
        return self._channel_def.camera_source_id

    @property
    def latest_raw(self) -> Optional[tuple]:
        """Latest ``(bboxes, PerceptionFrame)`` pair from the last successful
        inference. GIL-atomic read — no lock required."""
        return self._latest_raw

    def start(self) -> None:
        self._stop.clear()
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # --- hot loop --------------------------------------------------------

    def _check_source_id(self, frame: PerceptionFrame) -> bool:
        if (
            frame.source_id == self._capture.source_id
            and frame.source_id == self._channel_def.camera_source_id
        ):
            return True
        self.source_id_assertions += 1
        _hit(self._profiler, f"perception.{self.source_id}.source_id_assertion")
        if self._logger is not None:
            try:
                self._logger.error(
                    f"[perception] source_id assertion failed: "
                    f"frame={frame.source_id!r} "
                    f"capture={self._capture.source_id!r} "
                    f"channel={self._channel_def.camera_source_id!r}"
                )
            except Exception:
                pass
        return False

    def _maybe_emit_exit_edge(self, ts: float, in_exit_now: bool) -> None:
        if self._on_exit_edge is None:
            return
        if in_exit_now and not self._was_in_exit:
            try:
                self._on_exit_edge(ts)
            except Exception:
                pass
        self._was_in_exit = in_exit_now

    def _maybe_log_attribution(
        self,
        in_exit: bool,
        in_precise: bool,
        in_exit_majority: bool,
        per_bbox_counts: list,
    ) -> None:
        """Log every frame where the piece is anywhere in the exit-union (so
        we capture both the "should jitter" and "should NOT jitter" cases).
        Each on-channel bbox is reported with n_drop / n_exit_only / n_precise
        / n_in_mask grid-point counts — these are the actual area-overlap
        numbers driving the in_exit_majority trigger. Channel section set
        sizes are appended so it's obvious if precise_sections is empty
        (which would silently degrade exit_only → full exit union).
        """
        if self._logger is None:
            return
        if not in_exit and not in_exit_majority:
            return
        ch = self._channel_def
        exit_only_size = len(ch.exit_sections - ch.precise_sections)
        bbox_strs = []
        for nd, ne, np_, nm, bbox in per_bbox_counts:
            x1, y1, x2, y2 = bbox
            total_grid = nd + ne + np_
            pct_e = (100.0 * ne / total_grid) if total_grid else 0.0
            pct_p = (100.0 * np_ / total_grid) if total_grid else 0.0
            bbox_strs.append(
                f"bbox=({x1},{y1},{x2},{y2}) n_drop={nd} n_exit_only={ne} "
                f"n_precise={np_} n_in_mask={nm} "
                f"({pct_e:.0f}%E/{pct_p:.0f}%P of regions)"
            )
        bbox_summary = " | ".join(bbox_strs) if bbox_strs else "(no on-channel bboxes)"
        try:
            self._logger.info(
                f"[perception ch={ch.channel_id} src={ch.camera_source_id}] "
                f"in_exit={in_exit} in_precise={in_precise} "
                f"in_exit_majority={in_exit_majority} | "
                f"section_sizes drop={len(ch.drop_sections)} "
                f"exit_union={len(ch.exit_sections)} "
                f"precise={len(ch.precise_sections)} "
                f"exit_only={exit_only_size} | "
                f"{bbox_summary}"
            )
        except Exception:
            pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.iterations += 1
            _hit(self._profiler, f"perception.{self.source_id}.iterations")
            try:
                frame = self._capture.latest_frame()
                if frame is None:
                    self._stop.wait(_NO_FRAME_SLEEP_S)
                    continue
                if frame.timestamp == self._last_frame_ts:
                    self._stop.wait(_IDLE_SLEEP_S)
                    continue
                if not self._check_source_id(frame):
                    # Hard fail to a safe state — write a neutral slot and
                    # keep retrying. A future change that flips the
                    # source_id will land us here loudly; correct system
                    # state stays "nothing detected" rather than "wrong
                    # detections."
                    self._slot.write(
                        ChannelState(
                            ts=frame.timestamp, in_drop=False, in_exit=False, n_pieces=0
                        )
                    )
                    self._last_frame_ts = frame.timestamp
                    self._stop.wait(_IDLE_SLEEP_S)
                    continue

                cycle_t0 = _now_ms()
                infer_t0 = cycle_t0
                bboxes = self._runtime.infer(
                    frame.bgr, conf_threshold=self._conf_threshold
                )
                infer_ms = _now_ms() - infer_t0

                attribute_t0 = _now_ms()
                in_drop, in_exit, in_precise, in_exit_majority, n_pieces, per_bbox_counts = attributeBboxes(
                    bboxes, self._channel_def
                )
                advance_clearance_deg = forwardClearanceToExitDeg(
                    bboxes, self._channel_def
                )
                attribute_ms = _now_ms() - attribute_t0

                state = ChannelState(
                    ts=frame.timestamp,
                    in_drop=in_drop,
                    in_exit=in_exit,
                    n_pieces=n_pieces,
                    in_precise=in_precise,
                    in_exit_majority=in_exit_majority,
                    advance_clearance_deg=advance_clearance_deg,
                )
                self._slot.write(state)
                self._latest_raw = (list(bboxes), frame)
                self._maybe_emit_exit_edge(frame.timestamp, in_exit)
                self._maybe_log_attribution(
                    in_exit, in_precise, in_exit_majority, per_bbox_counts
                )
                self._last_frame_ts = frame.timestamp
                self.inferences += 1

                cycle_ms = _now_ms() - cycle_t0
                _observe(self._runtime_stats, f"perception.{self.source_id}.cycle_ms", cycle_ms)
                _observe(self._runtime_stats, f"perception.{self.source_id}.infer_ms", infer_ms)
                _observe(
                    self._runtime_stats,
                    f"perception.{self.source_id}.attribute_ms",
                    attribute_ms,
                )
                _observe(
                    self._runtime_stats,
                    f"perception.{self.source_id}.frame_age_ms",
                    max(0.0, (time.time() - frame.timestamp) * 1000.0),
                )
                _hit(self._profiler, f"perception.{self.source_id}.inferred")

            except Exception as exc:
                self.errors += 1
                _hit(self._profiler, f"perception.{self.source_id}.errors")
                if self._logger is not None:
                    try:
                        self._logger.warning(
                            f"[perception] {self.source_id} loop error: {exc}"
                        )
                    except Exception:
                        pass
                self._stop.wait(0.1)
