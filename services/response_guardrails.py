from __future__ import annotations

import re
from typing import Any


DEFAULT_PTSD_BLOCKED_PHRASES = [
    "я понимаю, что тебе тяжело",
    "мне очень жаль, что ты через это проходишь",
    "твои чувства валидны",
]

SELF_HARM_PATTERNS = [
    "хочу умереть",
    "не хочу жить",
    "покончить с собой",
    "суицид",
    "самоубий",
    "убью себя",
    "навредить себе",
    "причинить себе вред",
    "self-harm",
    "self harm",
    "kill myself",
    "end my life",
    "suicide",
]

HARM_TO_OTHERS_PATTERNS = [
    "убью его",
    "убью ее",
    "убью их",
    "хочу убить",
    "навредить кому-то",
    "причинить вред другому",
    "сделаю больно кому-то",
    "kill him",
    "kill her",
    "kill them",
    "hurt someone",
    "hurt somebody",
]


def detect_crisis_signal(text: str) -> str | None:
    lowered = " ".join(str(text or "").lower().split())
    if not lowered:
        return None

    if any(pattern in lowered for pattern in SELF_HARM_PATTERNS):
        return "self_harm"

    if any(pattern in lowered for pattern in HARM_TO_OTHERS_PATTERNS):
        return "harm_to_others"

    return None


def build_crisis_support_response(kind: str) -> str:
    if kind == "harm_to_others":
        return (
            "Сейчас важнее всего не оставаться с этим импульсом один на один.\n\n"
            "Если есть риск, что ты можешь причинить вред другому человеку в ближайшее время, "
            "сразу отойди от того, чем можно навредить, выйди из контакта с человеком и срочно "
            "обратись в местные экстренные службы или к человеку рядом, который может вмешаться."
        )

    return (
        "Сейчас важнее всего не оставаться с этим одному.\n\n"
        "Если есть риск, что ты можешь навредить себе в ближайшее время, сразу обратись в местные "
        "экстренные службы или в ближайший пункт неотложной помощи и позови человека рядом. "
        "По возможности не оставайся один и убери от себя все, чем можно причинить себе вред."
    )


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
