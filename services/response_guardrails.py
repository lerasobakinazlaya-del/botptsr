from __future__ import annotations

import re
from typing import Any


DEFAULT_PTSD_BLOCKED_PHRASES = [
    "я понимаю, что тебе тяжело",
    "мне очень жаль, что ты через это проходишь",
    "твои чувства валидны",
]

PTSD_GUARDED_MODES = {"free_talk", "ptsd", "comfort"}
PTSD_HEAVY_TONES = {"overwhelmed", "anxious", "guarded"}
PTSD_MAX_SENTENCES = 4
PTSD_MAX_CHARS = 340

DIRECT_SELF_HARM_PATTERNS = [
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

THIRD_PARTY_CRISIS_PATTERNS = [
    "мой друг хочет умереть",
    "мой друг не хочет жить",
    "подруга хочет умереть",
    "друг хочет умереть",
    "мой близкий хочет умереть",
    "он хочет покончить с собой",
    "она хочет покончить с собой",
    "someone wants to kill themselves",
    "my friend wants to die",
]

AMBIGUOUS_CRISIS_PATTERNS = [
    "не хочу жить так",
    "лучше бы меня не было",
    "хочу исчезнуть",
    "хочу пропасть",
    "мысли о смерти",
    "думаю о смерти",
    "не вижу смысла жить",
    "все бессмысленно",
]


def detect_crisis_signal(text: str) -> str | None:
    lowered = " ".join(str(text or "").lower().split())
    if not lowered:
        return None

    if any(pattern in lowered for pattern in DIRECT_SELF_HARM_PATTERNS):
        return "direct_self_harm"

    if any(pattern in lowered for pattern in THIRD_PARTY_CRISIS_PATTERNS):
        return "third_party_mention"

    if any(pattern in lowered for pattern in AMBIGUOUS_CRISIS_PATTERNS):
        return "ambiguous_crisis"

    return None


def build_crisis_support_response(kind: str) -> str:
    if kind != "direct_self_harm":
        return (
            "Если риск немедленный, важнее всего сразу обратиться за срочной реальной помощью "
            "и не оставаться с этим одному."
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
    if active_mode not in PTSD_GUARDED_MODES:
        return text
    if emotional_tone not in PTSD_HEAVY_TONES:
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

    for phrase in phrase_list:
        replacement = replacements.get(phrase.lower())
        if not replacement:
            continue
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        guarded = pattern.sub(replacement, guarded)

    question_count = guarded.count("?")
    if question_count > 1:
        first_index = guarded.find("?")
        guarded = guarded[: first_index + 1] + guarded[first_index + 1 :].replace("?", ".")

    return " ".join(guarded.split()).strip()


def tighten_ptsd_response(
    text: str,
    *,
    max_sentences: int = PTSD_MAX_SENTENCES,
    max_chars: int = PTSD_MAX_CHARS,
) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return normalized

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    compact = " ".join(sentence.strip() for sentence in sentences[:max_sentences] if sentence.strip())

    if len(compact) <= max_chars:
        return compact

    clipped = compact[:max_chars].rstrip(" ,;:-")
    last_break = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if last_break >= int(max_chars * 0.55):
        clipped = clipped[: last_break + 1]
    else:
        last_space = clipped.rfind(" ")
        if last_space >= int(max_chars * 0.55):
            clipped = clipped[:last_space]

    return clipped.rstrip(" ,;:-") + ("." if clipped and clipped[-1] not in ".!?" else "")


def analyze_response_style(text: str, *, blocked_phrases: list[str] | None = None) -> dict[str, Any]:
    normalized = str(text or "").strip()
    lowered = normalized.lower()
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]
    phrases = [phrase.strip() for phrase in (blocked_phrases or DEFAULT_PTSD_BLOCKED_PHRASES) if str(phrase).strip()]
    flagged = [phrase for phrase in phrases if phrase.lower() in lowered]
    return {
        "length": len(normalized),
        "question_count": normalized.count("?"),
        "sentence_count": len(sentences),
        "blocked_phrases": flagged,
        "looks_overloaded": len(normalized) > 450 or normalized.count("\n") > 4 or len(sentences) > PTSD_MAX_SENTENCES,
    }
