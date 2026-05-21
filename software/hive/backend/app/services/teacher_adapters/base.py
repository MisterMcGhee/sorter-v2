"""Adapter protocol for vision-model bbox detection.

Each adapter wraps one external model (or an entire provider family if they truly share an
identical request/response contract). Even when two models claim the same OpenAI-compatible
API, their quirks — coordinate scale, JSON discipline, supported request fields — diverge
enough that we want isolation rather than ``if model_id == ...`` branches scattered through
one detector. Adapters return ``TeacherDetectionResult`` in a normalized shape so the worker,
the sync rerun endpoint, and the compare page can treat them interchangeably.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class TeacherRateLimitError(RuntimeError):
    """Raised by adapters when the upstream provider returns 429.

    ``retry_after_s`` carries the Retry-After hint from the provider when present so the
    worker's backoff loop can honour it instead of guessing.
    """

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


@dataclass
class TeacherDetectionResult:
    model: str
    algorithm: str                   # algo string written onto Sample.detection_algorithm
    bboxes: list[list[int]]          # pixel coords, [x1, y1, x2, y2], sorted by confidence
    score: float                     # confidence of the top detection (0..1)
    count: int                       # len(bboxes); kept for symmetry with the sample schema
    image_width: int
    image_height: int
    detections: list[dict[str, Any]] # full records with kind/description/confidence
    cost_usd: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    elapsed_ms: int                  # adapter wall-clock latency for the model call
    adapter_kind: str = ""           # "openrouter_chat" | "perceptron" — for UI / debugging
    raw_response: dict[str, Any] | None = field(default=None, repr=False)

    def to_payload(self) -> dict[str, Any]:
        """Shape the worker + endpoints have been consuming since before adapters existed."""
        return {
            "algorithm": self.algorithm,
            "model": self.model,
            "bboxes": self.bboxes,
            "score": self.score,
            "count": self.count,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "detections": self.detections,
            "cost_usd": self.cost_usd,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "elapsed_ms": self.elapsed_ms,
            "adapter_kind": self.adapter_kind,
        }


@runtime_checkable
class TeacherAdapter(Protocol):
    model_id: str          # OpenRouter or provider slug, e.g. "google/gemini-3-flash-preview"
    display_name: str      # short label shown in the UI dropdown / compare page rows
    adapter_kind: str      # provider category — used by UI to show "OpenRouter (chat)" etc.
    notes: str             # one-sentence hint shown next to the model on the compare page
    # Which encrypted API key on the User model this adapter consumes. The router resolves
    # this to the actual decrypted secret before calling detect(). Either "openrouter" or
    # "perceptron" today; add more as new providers come online.
    secret_kind: str
    # Max in-flight requests the worker is willing to keep open against this provider at
    # any given moment. Picked from the provider's published rate limits and parallelism
    # guidance — see e.g. https://docs.perceptron.inc/scaling. Defaults to a conservative
    # value; subclasses override when the provider explicitly tolerates more.
    max_concurrent: int
    # Minimum spacing between *consecutive* calls to this provider (in seconds), regardless
    # of how many threads want to call. Prevents the worker from sprinting at a fresh
    # quota window and tripping a per-second cap.
    min_interval_s: float

    def detect(
        self,
        *,
        image_bytes: bytes,
        zone: str,
        api_key: str,
        public_app_url: str,
        override_prompt: str | None = None,
    ) -> TeacherDetectionResult: ...
