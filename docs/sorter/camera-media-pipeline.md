---
layout: default
title: Camera Media Pipeline
parent: Sorter
section: sorter
---

# Camera Media Pipeline

The sorter treats camera video as two separate products:

- **Computer-vision frames:** Python/OpenCV-owned, full quality, used for detection,
  tracking, samples, calibration, and still captures.
- **Browser live preview:** WebRTC transport, hardware encoded where possible,
  optimized for low latency and stable inspection quality.

Python should stay the **control plane**. It owns camera assignment, capture mode,
picture settings, detection orchestration, incidents, sample capture, and metadata.
It should not be the long-term 4K live-video encoder.

## Target Architecture

```text
Camera
  -> Python/OpenCV CaptureThread
       -> detection / tracking / samples / high-quality stills
       -> metadata events

Camera
  -> platform media pipeline
       -> hardware H.264 encoder
       -> WebRTC browser stream

Browser
  -> video element
  -> metadata overlay canvas/SVG for boxes, zones, incidents, telemetry
```

The browser overlay is deliberately not burned into the video. That keeps the video
encoder focused on the image and lets the UI render boxes/zones crisply at display
resolution.

## Platform Targets

### macOS

Preferred stack:

```text
avfvideosrc -> videoconvert -> vtenc_h264_hw -> h264parse -> WebRTC handoff
```

The encoder target is Apple VideoToolbox through GStreamer.

### Orange Pi 5 / RK3588

Preferred stack:

```text
v4l2src -> videoconvert/RGA -> mpph264enc or rkv4l2h264enc -> h264parse -> WebRTC handoff
```

The encoder target is the Rockchip media pipeline. Element names vary by image,
so the planner accepts `mpph264enc`, `rkv4l2h264enc`, or `v4l2h264enc`.

## Current Implementation Marker

`GET /api/cameras/media-pipeline` reports the desired backend per camera role.
It returns:

- selected backend: `gstreamer_hardware` or the current `python_aiortc` fallback
- required tools and GStreamer elements
- the planned GStreamer pipeline stage
- why the system is falling back

This endpoint is the migration boundary: UI and runtime code should depend on this
capability state instead of hardcoding transport decisions across components.

## Migration Rules

- Prefer lowering preview FPS over lowering capture resolution.
- Keep full-resolution still capture available even when live preview is reduced.
- Do not duplicate camera opens for normal operation.
- Do not burn overlays into the long-term live-video stream.
- Keep Python aiortc as a fallback, not as the final 4K preview foundation.
