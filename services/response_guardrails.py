from __future__ import annotations

import re
from typing import Any


DEFAULT_PTSD_BLOCKED_PHRASES = [
    "я понимаю, что тебе тяжело",
    "мне очень жаль, что ты через это проходишь",
    "твои чувства валидны",
]


def apply_ptsd_response_guardrails(
    text: str,
    *,
    active_mode: str,
    emotional_tone: str,
    enabled: bool,
    blocked_phrases: list[str] | None = None,
) -> str:
    if not enabled:
        return text
    if active_mode not in {"free_talk", "ptsd", "comfort"}:
        return text
    if emotional_tone not in {"overwhelmed", "anxious", "guarded"}:
        return text

    guarded = str(text or "").strip()
    if not guarded:
        return guarded

    phrase_list = [phrase.strip() for phrase in (blocked_phrases or DEFAULT_PTSD_BLOCKED_PHRASES) if str(phrase).strip()]
    replacements = {
        "я понимаю, что тебе тяжело": "слышу, как тебе тяжело",
        "мне очень жаль, что ты через это проходишь": "это правда тяжело",
        "твои чувства валидны": "твоя реакция понятна",
    }

    lowered = guarded.lower()
    for phrase in phrase_list:
        replacement = replacements.get(phrase.lower())
        if not replacement:
            continue
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        guarded = pattern.sub(replacement, guarded)
        lowered = guarded.lower()

    question_count = guarded.count("?")
    if question_count > 1:
        first_index = guarded.find("?")
        guarded = guarded[: first_index + 1] + guarded[first_index + 1 :].replace("?", ".")

    return " ".join(guarded.split()).strip()


def analyze_response_style(text: str, *, blocked_phrases: list[str] | None = None) -> dict[str, Any]:
    normalized = str(text or "").strip()
    lowered = normalized.lower()
    phrases = [phrase.strip() for phrase in (blocked_phrases or DEFAULT_PTSD_BLOCKED_PHRASES) if str(phrase).strip()]
    flagged = [phrase for phrase in phrases if phrase.lower() in lowered]
    return {
        "length": len(normalized),
        "question_count": normalized.count("?"),
        "blocked_phrases": flagged,
        "looks_overloaded": len(normalized) > 700 or normalized.count("\n") > 8,
    }
