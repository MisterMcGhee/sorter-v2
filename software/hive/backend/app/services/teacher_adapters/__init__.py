"""Registry of all supported teacher adapters.

Adding a new model in this file (and only here) is enough to surface it in the worker, the
sync rerun endpoint, the compare page, and the supported-models allow-list.
"""

from __future__ import annotations

from .base import TeacherAdapter, TeacherDetectionResult, TeacherRateLimitError
from .grok import GrokAdapter
from .openrouter_chat import OpenRouterChatAdapter
from .perceptron import PerceptronAdapter


# Note ordering: the first Gemini entry is the default if a user hasn't picked anything else.
_REGISTRY: dict[str, TeacherAdapter] = {}


def register(adapter: TeacherAdapter) -> None:
    _REGISTRY[adapter.model_id] = adapter


# --- Gemini family (Google) — the calibration baseline. -----------------------------------
register(OpenRouterChatAdapter(
    model_id="google/gemini-3-flash-preview",
    display_name="Gemini 3 Flash (preview)",
    notes="Default. Fast, cheap, strong on bbox coordinates.",
))
register(OpenRouterChatAdapter(
    model_id="google/gemini-3.1-flash-lite-preview",
    display_name="Gemini 3.1 Flash Lite",
    notes="Cheapest Gemini path. Lower fidelity than 3 Flash on dense scenes.",
))
register(OpenRouterChatAdapter(
    model_id="google/gemini-3.1-pro-preview",
    display_name="Gemini 3.1 Pro (preview)",
    notes="Pro tier. More reliable on edge cases, ~10× cost.",
))
register(OpenRouterChatAdapter(
    model_id="google/gemini-3.5-flash",
    display_name="Gemini 3.5 Flash",
    notes="Newer Flash. ~5× input price of Gemini 3 Flash; check quality wins.",
))


# --- Cross-vendor candidates worth comparing against Gemini. ------------------------------
register(OpenRouterChatAdapter(
    model_id="qwen/qwen3.6-flash",
    display_name="Qwen 3.6 Flash",
    notes="Alibaba's vision flash. Cheap; Qwen-VL is known to be strong at grounding.",
))
register(GrokAdapter(
    model_id="x-ai/grok-4.3",
    display_name="xAI Grok 4.3",
    notes="Reasoning + vision. Returns XYXY 0-1000 (not Gemini's YXYX) — handled here.",
))
register(OpenRouterChatAdapter(
    # OpenRouter uses the "~" prefix for floating "latest" aliases that re-target as the
    # provider releases new Kimi snapshots — see the model card on openrouter.ai.
    model_id="~moonshotai/kimi-latest",
    display_name="Moonshot Kimi (latest)",
    notes="Kimi K2-class vision. Long context. Unproven for bbox tasks.",
))
register(OpenRouterChatAdapter(
    model_id="xiaomi/mimo-v2.5",
    display_name="Xiaomi MiMo V2.5",
    notes="Native omnimodal; advertised Pro-level perception at half cost.",
))
register(OpenRouterChatAdapter(
    model_id="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    display_name="NVIDIA Nemotron 3 Nano Omni (free)",
    notes="Free tier. Hybrid MoE; worth a comparison run for the cost of nothing.",
))


# --- Purpose-built grounding model. -------------------------------------------------------
register(PerceptronAdapter())


def list_adapters() -> list[TeacherAdapter]:
    """Stable ordering — registration order matches the compare page's row order."""
    return list(_REGISTRY.values())


def get_adapter(model_id: str) -> TeacherAdapter | None:
    return _REGISTRY.get(model_id)


def supported_model_ids() -> tuple[str, ...]:
    return tuple(_REGISTRY.keys())


def default_model_id() -> str:
    # First registered entry is the default; today that's Gemini 3 Flash.
    return next(iter(_REGISTRY))


__all__ = [
    "TeacherAdapter",
    "TeacherDetectionResult",
    "TeacherRateLimitError",
    "default_model_id",
    "get_adapter",
    "list_adapters",
    "register",
    "supported_model_ids",
]
