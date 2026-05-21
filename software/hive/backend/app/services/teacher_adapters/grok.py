"""xAI Grok adapter — XYXY 0-1000 coordinate convention.

Grok follows the JSON shape we ask for in the Gemini prompt but ignores the
``[y_min, x_min, y_max, x_max]`` axis ordering and emits ``[x_min, y_min, x_max, y_max]``
instead. Without this adapter the boxes look "shifted" because the generic chat parser
swaps the axes.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from .base import TeacherDetectionResult
from .openrouter_chat import (
    OpenRouterChatAdapter,
    _call_openrouter_vision,
    _decode_image_size,
    _parse_normalized_bbox,
    _build_user_prompt,
)


class GrokAdapter(OpenRouterChatAdapter):
    """Grok-specific bbox parsing (XYXY instead of Gemini's YXYX)."""

    adapter_kind = "grok"

    def detect(
        self,
        *,
        image_bytes: bytes,
        zone: str,
        api_key: str,
        public_app_url: str,
        override_prompt: str | None = None,
    ) -> TeacherDetectionResult:
        width, height = _decode_image_size(image_bytes)
        if width <= 0 or height <= 0:
            raise RuntimeError("Sample image has zero dimensions")

        prompt = override_prompt if override_prompt else _build_user_prompt(width, height, zone)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        start = time.monotonic()
        payload, usage, raw = _call_openrouter_vision(
            api_key=api_key,
            model=self.model_id,
            prompt=prompt,
            image_b64=image_b64,
            public_app_url=public_app_url,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)

        sx = width / 1000.0
        sy = height / 1000.0
        raw_detections = payload.get("detections", []) if isinstance(payload, dict) else []
        detections: list[dict[str, Any]] = []
        for det in raw_detections:
            if not isinstance(det, dict):
                continue
            normalized = _parse_normalized_bbox(det.get("bbox"))
            if normalized is None:
                continue
            v0, v1, v2, v3 = normalized
            # XYXY (Grok) instead of YXYX (Gemini). Parse v0/v2 as x, v1/v3 as y.
            x1n, x2n = sorted((v0, v2))
            y1n, y2n = sorted((v1, v3))
            x1 = int(max(0.0, min(1000.0, x1n)) * sx)
            y1 = int(max(0.0, min(1000.0, y1n)) * sy)
            x2 = int(max(0.0, min(1000.0, x2n)) * sx)
            y2 = int(max(0.0, min(1000.0, y2n)) * sy)
            if x2 <= x1 or y2 <= y1:
                continue
            try:
                confidence = float(det.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            if confidence < 0.5:
                continue
            kind_raw = str(det.get("kind", "lego")).strip().lower()
            kind = kind_raw if kind_raw in {"lego", "foreign"} else "lego"
            detections.append(
                {
                    "kind": kind,
                    "description": str(det.get("description", "piece")).strip() or "piece",
                    "bbox": [x1, y1, x2, y2],
                    "confidence": confidence,
                }
            )

        detections.sort(key=lambda d: d["confidence"], reverse=True)
        bboxes = [d["bbox"] for d in detections]
        score = detections[0]["confidence"] if detections else 0.0

        cost_usd: float | None = None
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        if isinstance(usage, dict):
            cv = usage.get("cost")
            if isinstance(cv, (int, float)) and not isinstance(cv, bool):
                cost_usd = float(cv)
            pt = usage.get("prompt_tokens")
            if isinstance(pt, int) and not isinstance(pt, bool):
                prompt_tokens = pt
            ct = usage.get("completion_tokens")
            if isinstance(ct, int) and not isinstance(ct, bool):
                completion_tokens = ct

        try:
            raw_text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raw_text = None

        return TeacherDetectionResult(
            model=self.model_id,
            algorithm="grok_vision",
            bboxes=bboxes,
            score=score,
            count=len(bboxes),
            image_width=width,
            image_height=height,
            detections=detections,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=elapsed_ms,
            adapter_kind=self.adapter_kind,
            raw_response={"text": raw_text, "full": raw} if raw_text else raw,
        )
