"""Per-channel perception state — what the coordinator reads.

The slot stores booleans, not bboxes. Region attribution happens on the
inference thread; the coordinator gets a finished verdict. Single-ref
atomic write keeps the slot lock-free.
"""

from __future__ import annotations

from dataclasses import dataclass


EMPTY_STATE_TS = 0.0


@dataclass(frozen=True)
class ChannelState:
    """The only thing the coordinator reads per channel.

    `ts == EMPTY_STATE_TS` means the slot has never been written (the
    inference worker has not produced its first frame yet) — treat as
    "no information."
    """

    ts: float
    in_drop: bool
    in_exit: bool
    n_pieces: int
    # Forward distance (output degrees) from the most-forward on-channel piece
    # to the near edge of the exit zone — the largest advance possible without
    # pushing a piece into the exit zone. ``None`` when there is no on-channel
    # piece or the channel has no exit arc. The cascade's ADVANCE caps its move
    # to this so a free drop-zone advance never shoves a leading piece through
    # the exit, bypassing the downstream-gated exit handling.
    advance_clearance_deg: float | None = None


EMPTY_STATE = ChannelState(ts=EMPTY_STATE_TS, in_drop=False, in_exit=False, n_pieces=0)


class LatestStateSlot:
    """Single atomic-ref slot. Producer overwrites, consumers read whatever
    the most recent write was. Tuple/object assignment is atomic under the
    GIL, so no lock is needed."""

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state: ChannelState = EMPTY_STATE

    def write(self, state: ChannelState) -> None:
        self._state = state

    def read(self) -> ChannelState:
        return self._state

    @property
    def has_data(self) -> bool:
        return self._state.ts != EMPTY_STATE_TS
