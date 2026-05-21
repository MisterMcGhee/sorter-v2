"""Camera media-pipeline planning.

The sorter still uses Python/OpenCV frames for detection and high-quality stills.
Live browser video, however, should move toward a hardware-encoded media path:
Python controls it, but does not software-encode every 4K preview frame.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable


DEFAULT_PREVIEW_FPS = 12.0
DEFAULT_H264_BITRATE_BPS = 12_000_000

_MACOS_REQUIRED_GST_ELEMENTS = ("avfvideosrc", "videoconvert", "vtenc_h264_hw", "h264parse")
_ROCKCHIP_CAPTURE_ELEMENTS = ("v4l2src", "videoconvert", "h264parse")
_ROCKCHIP_ENCODER_CANDIDATES = ("mpph264enc", "rkv4l2h264enc", "v4l2h264enc")


@dataclass(frozen=True)
class MediaPipelineToolStatus:
    name: str
    available: bool
    path: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": self.available,
            "path": self.path,
        }


@dataclass(frozen=True)
class CameraMediaPipelinePlan:
    role: str
    requested_backend: str
    selected_backend: str
    platform: str
    source: int | str | None
    width: int
    height: int
    capture_fps: int
    preview_fps: float
    transport: str
    encoder: str | None
    uses_hardware_encoder: bool
    can_launch_hardware_pipeline: bool
    pipeline: list[str] = field(default_factory=list)
    tools: list[MediaPipelineToolStatus] = field(default_factory=list)
    gst_elements: list[MediaPipelineToolStatus] = field(default_factory=list)
    fallback_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "requested_backend": self.requested_backend,
            "selected_backend": self.selected_backend,
            "platform": self.platform,
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "capture_fps": self.capture_fps,
            "preview_fps": self.preview_fps,
            "transport": self.transport,
            "encoder": self.encoder,
            "uses_hardware_encoder": self.uses_hardware_encoder,
            "can_launch_hardware_pipeline": self.can_launch_hardware_pipeline,
            "pipeline": list(self.pipeline),
            "tools": [tool.to_dict() for tool in self.tools],
            "gst_elements": [element.to_dict() for element in self.gst_elements],
            "fallback_reason": self.fallback_reason,
            "notes": list(self.notes),
        }


def requested_media_backend() -> str:
    raw = os.getenv("SORTER_CAMERA_MEDIA_BACKEND", "auto").strip().lower()
    if raw in {"auto", "python", "gstreamer"}:
        return raw
    return "auto"


def _command_status(name: str) -> MediaPipelineToolStatus:
    path = shutil.which(name)
    return MediaPipelineToolStatus(name=name, available=bool(path), path=path)


@lru_cache(maxsize=128)
def _gst_element_available(element: str) -> bool:
    if shutil.which("gst-inspect-1.0") is None:
        return False
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", element],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _gst_element_status(
    name: str,
    *,
    available_fn: Callable[[str], bool] = _gst_element_available,
) -> MediaPipelineToolStatus:
    return MediaPipelineToolStatus(name=name, available=available_fn(name), path=None)


def _platform_kind() -> str:
    forced = os.getenv("SORTER_MEDIA_PLATFORM", "").strip().lower()
    if forced:
        return forced

    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "linux":
        compatible = ""
        try:
            compatible = (
                open("/proc/device-tree/compatible", "rb")
                .read()
                .decode("utf-8", errors="ignore")
                .lower()
            )
        except Exception:
            compatible = ""
        machine = platform.machine().lower()
        if "rk3588" in compatible or "rockchip" in compatible or "rk3588" in machine:
            return "rockchip_linux"
        return "linux"
    return system or "unknown"


def _source_description_for_gstreamer(source: int | str | None, platform_kind: str) -> list[str]:
    if source is None:
        return []
    if platform_kind == "macos" and isinstance(source, int):
        return ["avfvideosrc", f"device-index={source}"]
    if platform_kind in {"rockchip_linux", "linux"} and isinstance(source, int):
        return ["v4l2src", f"device=/dev/video{source}"]
    if isinstance(source, str):
        return ["uridecodebin", f"uri={source}"]
    return []


def _macos_plan(
    role: str,
    source: int | str | None,
    width: int,
    height: int,
    capture_fps: int,
    preview_fps: float,
    requested_backend_name: str,
    gst_available_fn: Callable[[str], bool],
) -> tuple[list[str], str | None, list[MediaPipelineToolStatus], list[str]]:
    elements = [_gst_element_status(name, available_fn=gst_available_fn) for name in _MACOS_REQUIRED_GST_ELEMENTS]
    source_stage = _source_description_for_gstreamer(source, "macos")
    pipeline = [
        *source_stage,
        "!",
        f"video/x-raw,width={width},height={height},framerate={int(round(preview_fps))}/1",
        "!",
        "videoconvert",
        "!",
        "vtenc_h264_hw",
        "realtime=true",
        "allow-frame-reordering=false",
        f"bitrate={DEFAULT_H264_BITRATE_BPS}",
        "!",
        "h264parse",
        "config-interval=1",
    ]
    notes = [
        "Target: Apple VideoToolbox hardware H.264 for browser preview; Python keeps capture/detection control.",
        "The final WebRTC handoff should attach this encoded stream to a media server or native GStreamer WebRTC sink.",
    ]
    return pipeline, "vtenc_h264_hw", elements, notes


def _rockchip_plan(
    role: str,
    source: int | str | None,
    width: int,
    height: int,
    capture_fps: int,
    preview_fps: float,
    requested_backend_name: str,
    gst_available_fn: Callable[[str], bool],
) -> tuple[list[str], str | None, list[MediaPipelineToolStatus], list[str]]:
    encoder_statuses = [
        _gst_element_status(name, available_fn=gst_available_fn)
        for name in _ROCKCHIP_ENCODER_CANDIDATES
    ]
    encoder = next((status.name for status in encoder_statuses if status.available), _ROCKCHIP_ENCODER_CANDIDATES[0])
    element_statuses = [
        _gst_element_status(name, available_fn=gst_available_fn)
        for name in _ROCKCHIP_CAPTURE_ELEMENTS
    ] + encoder_statuses
    source_stage = _source_description_for_gstreamer(source, "rockchip_linux")
    pipeline = [
        *source_stage,
        "!",
        f"video/x-raw,width={width},height={height},framerate={int(round(preview_fps))}/1",
        "!",
        "videoconvert",
        "!",
        encoder,
        f"bps={DEFAULT_H264_BITRATE_BPS}",
        "!",
        "h264parse",
        "config-interval=1",
    ]
    notes = [
        "Target: Rockchip MPP/RKVENC hardware H.264 on RK3588-class Orange Pi boards.",
        "Element names vary by OS image; the planner accepts mpph264enc, rkv4l2h264enc, or v4l2h264enc.",
    ]
    return pipeline, encoder, element_statuses, notes


def build_camera_media_pipeline_plan(
    role: str,
    *,
    source: int | str | None,
    width: int,
    height: int,
    capture_fps: int,
    preview_fps: float = DEFAULT_PREVIEW_FPS,
    requested_backend_name: str | None = None,
    gst_available_fn: Callable[[str], bool] = _gst_element_available,
    command_status_fn: Callable[[str], MediaPipelineToolStatus] = _command_status,
) -> CameraMediaPipelinePlan:
    requested = requested_backend_name or requested_media_backend()
    platform_kind = _platform_kind()
    tools = [command_status_fn("gst-launch-1.0"), command_status_fn("gst-inspect-1.0")]

    pipeline: list[str] = []
    encoder: str | None = None
    elements: list[MediaPipelineToolStatus] = []
    notes: list[str] = []

    if platform_kind == "macos":
        pipeline, encoder, elements, notes = _macos_plan(
            role,
            source,
            width,
            height,
            capture_fps,
            preview_fps,
            requested,
            gst_available_fn,
        )
    elif platform_kind in {"rockchip_linux", "linux"}:
        pipeline, encoder, elements, notes = _rockchip_plan(
            role,
            source,
            width,
            height,
            capture_fps,
            preview_fps,
            requested,
            gst_available_fn,
        )
    else:
        notes = ["No hardware media pipeline is known for this platform yet."]

    has_source = bool(_source_description_for_gstreamer(source, platform_kind))
    gst_tools_ready = all(tool.available for tool in tools)
    if platform_kind == "macos":
        required_elements = [element for element in elements if element.name in _MACOS_REQUIRED_GST_ELEMENTS]
        gst_elements_ready = all(element.available for element in required_elements)
    elif platform_kind in {"rockchip_linux", "linux"}:
        required_core = [element for element in elements if element.name in _ROCKCHIP_CAPTURE_ELEMENTS]
        any_encoder = any(element.available for element in elements if element.name in _ROCKCHIP_ENCODER_CANDIDATES)
        gst_elements_ready = all(element.available for element in required_core) and any_encoder
    else:
        gst_elements_ready = False

    can_launch_hardware = has_source and gst_tools_ready and gst_elements_ready and bool(encoder)
    fallback_reason: str | None = None
    selected = "gstreamer_hardware"
    if requested == "python":
        selected = "python_aiortc"
        fallback_reason = "SORTER_CAMERA_MEDIA_BACKEND=python forces the current Python aiortc path."
    elif not can_launch_hardware:
        selected = "python_aiortc"
        reasons: list[str] = []
        if not has_source:
            reasons.append("camera source is not representable as a local GStreamer source")
        if not gst_tools_ready:
            reasons.append("GStreamer command-line tools are missing")
        if not gst_elements_ready:
            reasons.append("required hardware encoder/capture elements are missing")
        if requested == "gstreamer":
            reasons.insert(0, "SORTER_CAMERA_MEDIA_BACKEND=gstreamer requested hardware pipeline")
        fallback_reason = "; ".join(reasons) if reasons else "hardware media pipeline is not ready"

    return CameraMediaPipelinePlan(
        role=role,
        requested_backend=requested,
        selected_backend=selected,
        platform=platform_kind,
        source=source,
        width=int(width),
        height=int(height),
        capture_fps=int(capture_fps),
        preview_fps=float(preview_fps),
        transport="webrtc",
        encoder=encoder if selected == "gstreamer_hardware" or requested == "gstreamer" else None,
        uses_hardware_encoder=selected == "gstreamer_hardware",
        can_launch_hardware_pipeline=can_launch_hardware,
        pipeline=pipeline,
        tools=tools,
        gst_elements=elements,
        fallback_reason=fallback_reason,
        notes=notes,
    )
