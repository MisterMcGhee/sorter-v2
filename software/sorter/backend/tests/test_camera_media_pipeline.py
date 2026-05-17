import unittest
from types import SimpleNamespace
from unittest.mock import patch

from vision.media_pipeline import (
    CameraMediaPipelinePlan,
    MediaPipelineToolStatus,
    build_camera_media_pipeline_plan,
)
from server import shared_state
from server.routers import cameras


def _tool(name: str, available: bool = True) -> MediaPipelineToolStatus:
    return MediaPipelineToolStatus(
        name=name,
        available=available,
        path=f"/usr/bin/{name}" if available else None,
    )


class CameraMediaPipelineTests(unittest.TestCase):
    def test_macos_with_videotoolbox_gstreamer_selects_hardware_backend(self) -> None:
        with patch.dict("os.environ", {"SORTER_MEDIA_PLATFORM": "macos", "SORTER_CAMERA_MEDIA_BACKEND": "auto"}):
            plan = build_camera_media_pipeline_plan(
                "classification_channel",
                source=3,
                width=3840,
                height=2160,
                capture_fps=30,
                gst_available_fn=lambda _name: True,
                command_status_fn=lambda name: _tool(name, True),
            )

        self.assertEqual("gstreamer_hardware", plan.selected_backend)
        self.assertTrue(plan.uses_hardware_encoder)
        self.assertEqual("vtenc_h264_hw", plan.encoder)
        self.assertIn("avfvideosrc", plan.pipeline)
        self.assertIn("vtenc_h264_hw", plan.pipeline)

    def test_missing_gstreamer_tools_falls_back_to_python(self) -> None:
        with patch.dict("os.environ", {"SORTER_MEDIA_PLATFORM": "macos", "SORTER_CAMERA_MEDIA_BACKEND": "auto"}):
            plan = build_camera_media_pipeline_plan(
                "classification_channel",
                source=3,
                width=3840,
                height=2160,
                capture_fps=30,
                gst_available_fn=lambda _name: True,
                command_status_fn=lambda name: _tool(name, False),
            )

        self.assertEqual("python_aiortc", plan.selected_backend)
        self.assertFalse(plan.can_launch_hardware_pipeline)
        self.assertIn("GStreamer command-line tools are missing", plan.fallback_reason or "")

    def test_rockchip_selects_available_mpp_encoder(self) -> None:
        available = {"v4l2src", "videoconvert", "h264parse", "mpph264enc"}
        with patch.dict("os.environ", {"SORTER_MEDIA_PLATFORM": "rockchip_linux", "SORTER_CAMERA_MEDIA_BACKEND": "auto"}):
            plan = build_camera_media_pipeline_plan(
                "c_channel_2",
                source=0,
                width=1920,
                height=1080,
                capture_fps=30,
                gst_available_fn=lambda name: name in available,
                command_status_fn=lambda name: _tool(name, True),
            )

        self.assertEqual("gstreamer_hardware", plan.selected_backend)
        self.assertEqual("mpph264enc", plan.encoder)
        self.assertIn("device=/dev/video0", plan.pipeline)

    def test_media_pipeline_endpoint_reports_active_role_plans(self) -> None:
        fake_service = SimpleNamespace(
            feeds={"classification_channel": object()},
            get_capture_mode_for_role=lambda role: {
                "width": 3840,
                "height": 2160,
                "fps": 30,
            },
        )
        fake_plan = CameraMediaPipelinePlan(
            role="classification_channel",
            requested_backend="auto",
            selected_backend="python_aiortc",
            platform="macos",
            source=3,
            width=3840,
            height=2160,
            capture_fps=30,
            preview_fps=12.0,
            transport="webrtc",
            encoder=None,
            uses_hardware_encoder=False,
            can_launch_hardware_pipeline=False,
        )

        with patch.object(shared_state, "camera_service", fake_service):
            with patch(
                "server.routers.cameras._read_machine_params_config",
                return_value=(None, {"cameras": {"classification_channel": 3}}),
            ):
                with patch(
                    "server.routers.cameras.build_camera_media_pipeline_plan",
                    return_value=fake_plan,
                ) as build:
                    response = cameras.get_camera_media_pipeline_status()

        self.assertTrue(response["ok"])
        self.assertEqual("python", response["architecture"]["control_plane"])
        self.assertIn("classification_channel", response["roles"])
        build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
