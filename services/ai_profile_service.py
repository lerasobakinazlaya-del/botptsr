from typing import Any


def resolve_ai_profile(ai_settings: dict[str, Any], active_mode: str) -> dict[str, Any]:
    mode_overrides = ai_settings.get("mode_overrides", {})
    override = mode_overrides.get(active_mode, {}) if isinstance(mode_overrides, dict) else {}

    model = str(override.get("model") or ai_settings.get("openai_model") or "gpt-4o-mini").strip()
    prompt_suffix = str(override.get("prompt_suffix") or "").strip()

    return {
        "model": model or "gpt-4o-mini",
        "temperature": _normalize_float(
            override.get("temperature", ai_settings.get("temperature", 0.9)),
            minimum=0.0,
            maximum=2.0,
            fallback=0.9,
        ),
        "memory_max_tokens": _normalize_int(
            override.get("memory_max_tokens", ai_settings.get("memory_max_tokens", 1500)),
            minimum=100,
            fallback=1500,
        ),
        "history_message_limit": _normalize_int(
            override.get("history_message_limit", ai_settings.get("history_message_limit", 20)),
            minimum=1,
            fallback=20,
        ),
        "timeout_seconds": _normalize_int(
            override.get("timeout_seconds", ai_settings.get("timeout_seconds", 20)),
            minimum=1,
            fallback=20,
        ),
        "max_retries": _normalize_int(
            override.get("max_retries", ai_settings.get("max_retries", 2)),
            minimum=0,
            fallback=2,
        ),
        "prompt_suffix": prompt_suffix,
    }


def _normalize_int(value: Any, *, minimum: int, fallback: int) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return fallback


def _normalize_float(
    value: Any,
    *,
    minimum: float,
    maximum: float,
    fallback: float,
) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, numeric))
