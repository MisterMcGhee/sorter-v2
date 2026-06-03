from __future__ import annotations

import time
from typing import Any

from defs.known_object import ClassificationStatus

CLASSIFICATION_UNRESOLVED_INCIDENT_KIND = "classification_unresolved"
CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND = "classification_multi_drop_collision"
CLASSIFICATION_INTAKE_TIMEOUT_INCIDENT_KIND = "classification_intake_request_timeout"
CLASSIFICATION_TRACK_LOST_INCIDENT_KIND = "classification_track_lost"
CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND = "classification_exit_stuck"


def classification_fallback_incident_kind(
    status: ClassificationStatus,
) -> str:
    if status == ClassificationStatus.multi_drop_fail:
        return CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND
    return CLASSIFICATION_UNRESOLVED_INCIDENT_KIND


def publish_classification_fallback_incident(
    gc: Any,
    *,
    piece: Any,
    status: ClassificationStatus,
    reason: str,
) -> bool:
    kind = classification_fallback_incident_kind(status)
    if _incident_handling_off(kind):
        return False

    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    piece_uuid = str(getattr(piece, "uuid", "") or "")
    if isinstance(active, dict):
        return active.get("kind") == kind and active.get("piece_uuid") == piece_uuid

    status_value = getattr(status, "value", str(status))
    tracked_global_id = getattr(piece, "tracked_global_id", None)
    center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
    exit_offset_deg = getattr(piece, "classification_channel_exit_offset_deg", None)
    payload: dict[str, Any] = {
        "kind": kind,
        "severity": (
            "critical"
            if kind == CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND
            else "warning"
        ),
        "status": "waiting_for_operator",
        "awaiting_operator": True,
        "scope": "classification",
        "channel": "c4",
        "role": "classification_channel",
        "channel_label": "C4",
        "piece_uuid": piece_uuid,
        "piece_short": piece_uuid[:8],
        "classification_status": status_value,
        "reason": str(reason),
        "triggered_at": time.time(),
        "rule": (
            "multiple_pieces_at_classification_drop"
            if kind == CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND
            else "classification_fell_back_before_drop"
        ),
        "resolution": "operator_review_classification_fallback_then_clear",
    }
    if isinstance(tracked_global_id, int):
        payload["tracked_global_id"] = int(tracked_global_id)
        payload["track_id"] = int(tracked_global_id)
    if isinstance(center_deg, (int, float)):
        payload["center_deg"] = float(center_deg)
    if isinstance(exit_offset_deg, (int, float)):
        payload["exit_offset_deg"] = float(exit_offset_deg)
    if kind == CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND:
        payload["operator_message"] = (
            "Multiple pieces reached the C4 drop area together. Inspect before continuing."
        )
    else:
        payload["operator_message"] = (
            "Classification fell back before the drop. Review if this repeats."
        )

    runtime_stats.setActiveIncident(payload)
    return True


def publish_classification_intake_timeout_incident(
    gc: Any,
    *,
    elapsed_s: float,
) -> bool:
    kind = CLASSIFICATION_INTAKE_TIMEOUT_INCIDENT_KIND
    if _incident_handling_off(kind):
        return False

    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    if isinstance(active, dict):
        return active.get("kind") == kind

    runtime_stats.setActiveIncident(
        {
            "kind": kind,
            "severity": "warning",
            "status": "waiting_for_operator",
            "awaiting_operator": True,
            "scope": "classification",
            "channel": "c4",
            "role": "classification_channel",
            "channel_label": "C4",
            "triggered_at": time.time(),
            "timeout_ms": int(max(0.0, float(elapsed_s)) * 1000.0),
            "rule": "c4_requested_piece_but_no_intake_track_arrived",
            "resolution": "operator_check_c3_to_c4_handoff_then_clear",
            "operator_message": (
                "C4 requested a piece from C3, but no intake track arrived before the timeout."
            ),
        }
    )
    return True


def publish_classification_track_lost_incident(
    gc: Any,
    *,
    piece: Any,
    reason: str,
) -> bool:
    kind = CLASSIFICATION_TRACK_LOST_INCIDENT_KIND
    if _incident_handling_off(kind):
        return False

    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    piece_uuid = str(getattr(piece, "uuid", "") or "")
    if isinstance(active, dict):
        return active.get("kind") == kind and active.get("piece_uuid") == piece_uuid

    status = getattr(getattr(piece, "classification_status", None), "value", None)
    tracked_global_id = getattr(piece, "tracked_global_id", None)
    payload: dict[str, Any] = {
        "kind": kind,
        "severity": "warning",
        "status": "waiting_for_operator",
        "awaiting_operator": True,
        "scope": "classification",
        "channel": "c4",
        "role": "classification_channel",
        "channel_label": "C4",
        "piece_uuid": piece_uuid,
        "piece_short": piece_uuid[:8],
        "classification_status": str(status or ""),
        "reason": str(reason),
        "triggered_at": time.time(),
        "rule": "meaningful_c4_track_expired_from_stale_zone",
        "resolution": "operator_check_c4_tracking_or_clear_if_expected",
        "operator_message": (
            "A C4 track with captured evidence expired before the normal drop flow completed."
        ),
    }
    if isinstance(tracked_global_id, int):
        payload["tracked_global_id"] = int(tracked_global_id)
        payload["track_id"] = int(tracked_global_id)
    runtime_stats.setActiveIncident(payload)
    return True


def publish_classification_exit_stuck_incident(
    gc: Any,
    *,
    piece: Any,
    jitter_attempts: int,
    converge_ms: float,
) -> bool:
    """Stall-watchdog incident: the C4 state machine made NO transition for the
    watchdog window while perception still reads a piece on the channel — the
    flow is wedged in some state. This is the ONLY remaining publisher of
    ``classification_exit_stuck``; the discharge give-up path no longer raises an
    incident (it settles and auto-credits instead). So any incident of this kind
    is unambiguously the stall watchdog — the payload also carries
    ``source="stall_watchdog"`` to make that explicit in logs/UI. Auto-clears
    when perception sees the channel clear."""
    kind = CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND
    if _incident_handling_off(kind):
        return False

    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    if isinstance(active, dict) and active.get("kind") == kind:
        return True

    piece_uuid = str(getattr(piece, "uuid", "") or "")
    payload: dict[str, Any] = {
        "kind": kind,
        "source": "stall_watchdog",
        "severity": "critical",
        "status": "waiting_for_operator",
        "awaiting_operator": True,
        "scope": "classification",
        "channel": "c4",
        "role": "classification_channel",
        "channel_label": "C4",
        "piece_uuid": piece_uuid,
        "piece_short": piece_uuid[:8],
        "jitter_attempts": int(jitter_attempts),
        "stalled_ms": float(converge_ms),
        "triggered_at": time.time(),
        "rule": "c4_no_state_transition_with_piece_on_channel",
        "resolution": "operator_clear_stuck_c4_piece_then_auto_resumes",
        "operator_message": (
            "The C4 classification flow stopped making progress with a piece still "
            "on the channel. Remove the piece (or clear the jam) to continue."
        ),
    }
    runtime_stats.setActiveIncident(payload)
    return True


def clear_classification_exit_stuck_incident(gc: Any) -> None:
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
        try:
            runtime_stats.clearActiveIncident(
                kind=CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND
            )
        except Exception:
            pass


def _incident_handling_off(kind: str) -> bool:
    try:
        from toml_config import incidentHandlingOff

        return bool(incidentHandlingOff(kind))
    except Exception:
        return False
