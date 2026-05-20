"""Generic OpenAI-chat-compatible vision adapter routed through OpenRouter.

Covers any model that accepts the standard
``messages=[{system}, {user: [{type: text}, {type: image_url}]}]`` request and returns the
detection JSON inline. The Gemini-family prompt asks for ``[y_min, x_min, y_max, x_max]`` on
a 0-1000 scale — Gemini was trained for exactly this and other "compatible" models we point
at it tend to follow along because the prompt is precise. Where a model diverges (Qwen's
native grounding format, for instance) the parser still salvages anything that pattern-matches
a bbox via :func:`_parse_normalized_bbox`.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from .base import TeacherAdapter, TeacherDetectionResult, TeacherRateLimitError


logger = logging.getLogger(__name__)


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_TIMEOUT_S = 45.0


SYSTEM_PROMPT = (
    "You are a precise object detector for a LEGO sorting machine. The machine "
    "is expected to process LEGO pieces but it also needs to notice anything "
    "else that ended up in the workflow — screws, coins, pebbles, plastic "
    "fragments, tape, hair, wrappers, any foreign object. Detect LEGO pieces "
    "AND non-LEGO items with equal attention. "
    "Respond with valid JSON only — no markdown, no prose, no explanations."
)


def _decode_image_size(image_bytes: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        return int(img.width), int(img.height)


def _iter_balanced_json_objects(text: str):
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(text)):
            current = text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : end + 1]
                    break


def _salvage_detection_payload(raw: str) -> dict[str, Any] | None:
    detections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in _iter_balanced_json_objects(raw):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict) or "bbox" not in parsed:
            continue
        if _parse_normalized_bbox(parsed.get("bbox")) is None:
            continue
        key = json.dumps(parsed, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        detections.append(parsed)
    if not detections:
        return None
    return {"detections": detections}


def _extract_json(text: str) -> dict[str, Any]:
    import re
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("Model response did not contain JSON.")
    raw = match.group()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            salvaged = _salvage_detection_payload(raw)
            if salvaged is not None:
                logger.warning(
                    "Model response contained malformed JSON; salvaged %s detection objects.",
                    len(salvaged["detections"]),
                )
                return salvaged
            raise


def _parse_normalized_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if isinstance(bbox, (list, tuple)):
        if len(bbox) < 4:
            return None
        try:
            v0, v1, v2, v3 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            return None
        return v0, v1, v2, v3

    if isinstance(bbox, str):
        text = bbox.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return _parse_normalized_bbox(parsed)

    if isinstance(bbox, dict):
        key_variants = (
            ("y_min", "x_min", "y_max", "x_max"),
            ("ymin", "xmin", "ymax", "xmax"),
            ("top", "left", "bottom", "right"),
            ("y1", "x1", "y2", "x2"),
            ("min_y", "min_x", "max_y", "max_x"),
        )
        for keys in key_variants:
            if not all(key in bbox for key in keys):
                continue
            try:
                return tuple(float(bbox[key]) for key in keys)  # type: ignore[return-value]
            except (TypeError, ValueError):
                return None

    return None


def _call_openrouter_vision(
    *,
    api_key: str,
    model: str,
    prompt: str,
    image_b64: str,
    public_app_url: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
        "usage": {"include": True},
    }
    body = json.dumps(payload).encode()
    request = Request(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": public_app_url,
            "X-Title": "Hive Teacher",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=OPENROUTER_API_TIMEOUT_S) as response:  # noqa: S310
            data = json.loads(response.read().decode())
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            err = json.loads(raw)
            message = err.get("error", {}).get("message") or err.get("message")
        except json.JSONDecodeError:
            message = None
        if exc.code == 429:
            retry_after = None
            try:
                hdr = exc.headers.get("Retry-After")
                if hdr is not None:
                    retry_after = float(hdr)
            except (TypeError, ValueError):
                retry_after = None
            raise TeacherRateLimitError(
                f"OpenRouter rate-limited: {message or 'HTTP 429'}",
                retry_after_s=retry_after,
            ) from exc
        raise RuntimeError(f"OpenRouter HTTP {exc.code}: {message or 'unknown error'}") from exc
    except URLError as exc:
        raise RuntimeError("OpenRouter could not be reached") from exc

    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("OpenRouter returned an unexpected response shape") from exc
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    return _extract_json(content.strip()), usage, data


def _build_user_prompt(width: int, height: int, zone: str) -> str:
    # Imported lazily to avoid a circular import — teacher_detector.py owns the prompts
    # because they're also used by the sync rerun preview test.
    from app.services.teacher_detector import gemini_prompt
    return gemini_prompt(width, height, zone=zone)


class OpenRouterChatAdapter:
    """Generic adapter for OpenAI-chat-shaped vision endpoints (the common case)."""

    adapter_kind = "openrouter_chat"
    secret_kind = "openrouter"
    # OpenRouter advertises ample per-account concurrency but the underlying providers
    # (Gemini, etc.) have their own per-second caps. 2 in-flight with 0.5s spacing keeps
    # us well below Gemini's typical 60 req/min default and matches the sorter rig's
    # MIN_API_INTERVAL_S so a live capture run alongside a backfill doesn't double-bill.
    max_concurrent = 2
    min_interval_s = 0.5

    def __init__(self, *, model_id: str, display_name: str, notes: str = "") -> None:
        self.model_id = model_id
        self.display_name = display_name
        self.notes = notes

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
            # The Gemini-style prompt asks for [y_min, x_min, y_max, x_max] on 0-1000.
            # Non-Gemini models *usually* obey when the prompt is this explicit; if a
            # specific model produces a different scale we'll write a dedicated subclass
            # rather than poison this generic path with auto-detection heuristics.
            y1 = int(max(0.0, min(1000.0, v0)) * sy)
            x1 = int(max(0.0, min(1000.0, v1)) * sx)
            y2 = int(max(0.0, min(1000.0, v2)) * sy)
            x2 = int(max(0.0, min(1000.0, v3)) * sx)
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

        # Capture the assistant's message text verbatim so the compare UI can show what the
        # model actually returned — invaluable when boxes look wrong and you can't tell
        # whether it's our parser or the model.
        try:
            raw_text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raw_text = None

        return TeacherDetectionResult(
            model=self.model_id,
            algorithm="gemini_sam",  # kept for backward compat with stored samples / training pipeline
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
