import unittest
from types import SimpleNamespace

import cv2
import numpy as np
from fastapi import HTTPException

from server import shared_state
from server.routers import detection


class _FakeVisionManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def debugFeederDetection(self, role: str, *, include_capture: bool = False):
        self.calls.append((role, include_capture))
        return {
            "camera": role,
            "algorithm": "gemini_sam",
            "found": False,
            "message": "No piece in frame.",
            "frame_resolution": [1280, 720],
            "candidate_bboxes": [],
            "bbox_count": 0,
            "bbox": None,
            "zone_bbox": None,
        }

    def getFeederOpenRouterModel(self) -> str:
        return "google/gemini-3-flash-preview"


def _synthetic_rotor_frame(phase_deg: float = 22.0) -> np.ndarray:
    image = np.zeros((720, 720, 3), dtype=np.uint8)
    center = (360, 360)
    cv2.circle(image, center, 330, (210, 210, 210), -1)
    cv2.circle(image, center, 125, (0, 0, 0), -1)
    for i in range(5):
        angle = np.deg2rad(phase_deg + i * 72.0)
        inner = (
            int(round(center[0] + np.cos(angle) * 130)),
            int(round(center[1] + np.sin(angle) * 130)),
        )
        outer = (
            int(round(center[0] + np.cos(angle) * 300)),
            int(round(center[1] + np.sin(angle) * 300)),
        )
        cv2.line(image, inner, outer, (105, 105, 105), 10, cv2.LINE_AA)
        cv2.line(image, inner, outer, (245, 245, 245), 3, cv2.LINE_AA)
    cv2.rectangle(image, (330, 360), (395, 720), (0, 0, 0), -1)
    return image


class DetectionRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_vision_manager = shared_state.vision_manager

    def tearDown(self) -> None:
        shared_state.vision_manager = self._old_vision_manager

    def test_debug_feeder_detection_accepts_classification_channel_role(self) -> None:
        fake_vision = _FakeVisionManager()
        shared_state.vision_manager = fake_vision

        payload = detection.debug_feeder_detection("carousel")

        self.assertTrue(payload["ok"])
        self.assertEqual("carousel", payload["camera"])
        self.assertEqual([("carousel", True)], fake_vision.calls)

    def test_debug_feeder_detection_rejects_unknown_role(self) -> None:
        shared_state.vision_manager = _FakeVisionManager()

        with self.assertRaises(HTTPException) as excinfo:
            detection.debug_feeder_detection("nope")

        self.assertEqual(400, excinfo.exception.status_code)
        self.assertEqual("Unsupported feeder role.", excinfo.exception.detail)

    def test_classification_channel_wall_phase_uses_live_frame(self) -> None:
        class FakeVision:
            def getCaptureThreadForRole(self, role: str):
                if role == "carousel":
                    return SimpleNamespace(
                        latest_frame=SimpleNamespace(raw=_synthetic_rotor_frame())
                    )
                return None

        shared_state.vision_manager = FakeVision()

        payload = detection.classification_channel_wall_phase()

        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["wall_count"], 4)
        self.assertAlmostEqual(22.0, payload["sector_offset_deg"], delta=3.0)


if __name__ == "__main__":
    unittest.main()
