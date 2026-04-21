from typing import Any


def resolve_ai_profile(
    ai_settings: dict[str, Any],
    active_mode: str,
    subscription_plan: str = "",
) -> dict[str, Any]:
    mode_overrides = ai_settings.get("mode_overrides", {})
    override = mode_overrides.get(active_mode, {}) if isinstance(mode_overrides, dict) else {}
    plan_overrides = ai_settings.get("plan_overrides", {})
    plan_key = str(subscription_plan or "").strip().lower()
    plan_override = plan_overrides.get(plan_key, {}) if plan_key and isinstance(plan_overrides, dict) else {}

    model = str(
        plan_override.get("model")
        or override.get("model")
        or ai_settings.get("openai_model")
        or "gpt-4o-mini"
    ).strip()
    prompt_suffix = "\n".join(
        part
        for part in (
            str(override.get("prompt_suffix") or "").strip(),
            str(plan_override.get("prompt_suffix") or "").strip(),
        )
        if part
    )

    return {
        "model": model or "gpt-4o-mini",
        "temperature": _normalize_float(
            plan_override.get("temperature", override.get("temperature", ai_settings.get("temperature", 0.9))),
            minimum=0.0,
            maximum=2.0,
            fallback=0.9,
        ),
        "max_completion_tokens": _normalize_int(
            plan_override.get("max_completion_tokens", override.get("max_completion_tokens", ai_settings.get("max_completion_tokens", 420))),
            minimum=32,
            fallback=420,
        ),
        "memory_max_tokens": _normalize_int(
            plan_override.get("memory_max_tokens", override.get("memory_max_tokens", ai_settings.get("memory_max_tokens", 1500))),
            minimum=100,
            fallback=1500,
        ),
        "history_message_limit": _normalize_int(
            plan_override.get("history_message_limit", override.get("history_message_limit", ai_settings.get("history_message_limit", 20))),
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
