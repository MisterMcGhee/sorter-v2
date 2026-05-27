"""Bbox → (in_drop, in_exit) attribution.

Pure functions. Called by ``InferenceWorker`` on each frame to convert
raw YOLO output into the boolean channel state the coordinator consumes.

The "section" math matches the legacy ``subsystems.feeder.analysis`` logic
(360 single-degree sections around the channel center). The legacy module
is not imported here — perception stands on its own — but the saved-arc
data format is shared, and the function below is regression-tested against
the legacy ``getBboxSections`` to confirm equivalence at the bbox level.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np

from .channel import ChannelDef, SECTION_COUNT, SECTION_DEG


Bbox = Tuple[int, int, int, int]


def bboxCenter(bbox: Bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def bboxInsideChannelMask(bbox: Bbox, channel: ChannelDef) -> bool:
    cx, cy = bboxCenter(bbox)
    h, w = channel.mask.shape[:2]
    ix, iy = int(cx), int(cy)
    if not (0 <= ix < w and 0 <= iy < h):
        return False
    return bool(channel.mask[iy, ix])


def bboxSections(bbox: Bbox, channel: ChannelDef) -> frozenset[int]:
    """Section ids touched by a small set of sample points on the bbox.

    Nine samples (corners + edge midpoints + center) — enough to catch a
    bbox that straddles a section boundary without paying for a per-pixel
    scan.
    """
    x1, y1, x2, y2 = bbox
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    points = (
        (x1, y1), (x2, y1), (x1, y2), (x2, y2),
        (mx, y1), (mx, y2), (x1, my), (x2, my),
        (mx, my),
    )
    cx0, cy0 = channel.center
    r1 = channel.radius1_angle_image
    sections: set[int] = set()
    for px, py in points:
        angle = float(np.degrees(np.arctan2(py - cy0, px - cx0)))
        relative = (angle - r1) % 360.0
        sections.add(int(relative / SECTION_DEG) % SECTION_COUNT)
    return frozenset(sections)


def attributeBbox(bbox: Bbox, channel: ChannelDef) -> tuple[bool, bool]:
    """Return ``(in_drop, in_exit)`` for a single bbox on this channel.

    A bbox is "on" the channel only if its center lies inside the saved
    polygon mask. Off-channel bboxes attribute to neither region (they
    were noise leaking outside the channel polygon).
    """
    if not bboxInsideChannelMask(bbox, channel):
        return False, False
    sections = bboxSections(bbox, channel)
    in_drop = bool(sections & channel.drop_sections)
    in_exit = bool(sections & channel.exit_sections)
    return in_drop, in_exit


def _orderedCircularSections(sections: frozenset[int]) -> list[int]:
    """Sections walked in forward order, starting after the largest gap, so the
    first entry is the rear (entry) edge and the last is the forward edge.
    Mirrors ``subsystems.feeder.analysis._orderedCircularSections`` but stays
    standalone — perception does not import the legacy stack."""
    if not sections:
        return []
    normalized = sorted(int(s) % SECTION_COUNT for s in sections)
    if len(normalized) <= 1 or len(normalized) >= SECTION_COUNT:
        return normalized
    largest_gap_index = 0
    largest_gap = -1
    for index, section in enumerate(normalized):
        next_section = normalized[(index + 1) % len(normalized)]
        gap = (next_section - section) % SECTION_COUNT
        if gap > largest_gap:
            largest_gap = gap
            largest_gap_index = index
    start = normalized[(largest_gap_index + 1) % len(normalized)]
    return sorted(normalized, key=lambda s: (s - start) % SECTION_COUNT)


def exitNearEdgeSection(channel: ChannelDef) -> int | None:
    ordered = _orderedCircularSections(channel.exit_sections)
    return ordered[0] if ordered else None


def forwardClearanceToExitDeg(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> float | None:
    """Smallest forward distance (output degrees) from any on-channel piece to
    the near edge of the exit zone, i.e. how far the rotor can advance before
    the most-forward piece enters the exit zone. ``None`` when no piece is on
    the channel or the channel has no exit arc.

    Forward is the increasing-relative-angle direction (same convention as the
    section math and the forward motor sign). With 1°-wide sections the
    section-index delta is already the angle in degrees.
    """
    near = exitNearEdgeSection(channel)
    if near is None:
        return None
    best: int | None = None
    for bbox in bboxes:
        if not bboxInsideChannelMask(bbox, channel):
            continue
        for section in bboxSections(bbox, channel):
            dist = (near - section) % SECTION_COUNT
            if best is None or dist < best:
                best = dist
    if best is None:
        return None
    return float(best) * SECTION_DEG


def attributeBboxes(
    bboxes: Iterable[Bbox], channel: ChannelDef
) -> tuple[bool, bool, int]:
    """Aggregate over multiple bboxes. Returns ``(any_in_drop, any_in_exit,
    n_on_channel)`` so the slot can carry a simple count for debugging /
    UI without leaking bbox coordinates to the coordinator."""
    any_drop = False
    any_exit = False
    n_on_channel = 0
    for bbox in bboxes:
        if not bboxInsideChannelMask(bbox, channel):
            continue
        n_on_channel += 1
        sections = bboxSections(bbox, channel)
        if not any_drop and sections & channel.drop_sections:
            any_drop = True
        if not any_exit and sections & channel.exit_sections:
            any_exit = True
    return any_drop, any_exit, n_on_channel
