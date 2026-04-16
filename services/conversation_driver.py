from __future__ import annotations

import re


INTENTS = {
    "desire",
    "emotion",
    "fantasy",
    "resistance",
    "curiosity",
    "short_reply",
    "explicit_request",
    "confusion",
}

HEAVY_TONES = {"overwhelmed", "anxious", "guarded"}
LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")


def detect_intent(message: str) -> str:
    text = _normalize(message)
    if not text:
        return "short_reply"
    if _contains_any(text, CONFUSION_MARKERS):
        return "confusion"
    if _contains_any(text, RESISTANCE_MARKERS):
        return "resistance"
    if _is_short_reply(text):
        return "short_reply"
    if _contains_any(text, CURIOSITY_MARKERS) and "?" in text:
        return "curiosity"
    if _contains_any(text, EXPLICIT_REQUEST_MARKERS):
        return "explicit_request"
    if _contains_any(text, FANTASY_MARKERS):
        return "fantasy"
    if _contains_any(text, EMOTION_MARKERS):
        return "emotion"
    if _contains_any(text, DESIRE_MARKERS):
        return "desire"
    if _contains_any(text, CURIOSITY_MARKERS) or "?" in text:
        return "curiosity"
    return "curiosity"


def build_followup(intent: str, state: dict) -> str:
    normalized_intent = str(intent or "curiosity").strip().lower()
    if normalized_intent not in INTENTS:
        normalized_intent = "curiosity"

    intro = BASE_REFLECTIONS[normalized_intent]
    if _is_high_engagement(state):
        intro = PERSONALIZED_REFLECTIONS.get(normalized_intent, intro)

    emotional_tone = str((state or {}).get("emotional_tone") or "").strip().lower()
    if emotional_tone in HEAVY_TONES:
        intro = SOFT_REFLECTIONS.get(normalized_intent, intro)

    return f"{intro} {FOLLOWUP_QUESTIONS[normalized_intent]}".strip()


def apply_driver_guardrails(
    text: str,
    *,
    user_message: str,
    state: dict | None = None,
    intent: str | None = None,
) -> str:
    resolved_intent = intent or detect_intent(user_message)
    fallback = build_followup(resolved_intent, state or {})
    normalized = _normalize_with_breaks(text)
    if not normalized:
        return fallback

    if not _user_explicitly_requested_list(user_message):
        normalized = _collapse_list_shape(normalized)

    normalized = _trim_sentences(normalized, max_sentences=3)
    normalized = _limit_questions(normalized)
    if not normalized:
        return fallback

    if "?" not in normalized:
        question = _extract_question(fallback)
        normalized = _append_sentence(normalized, question)

    return normalized.strip()


DESIRE_MARKERS = (
    "хочу",
    "хочется",
    "тянет",
    "цепляет",
    "манит",
    "нравится",
    "привлекает",
    "заводит",
    "возбуждает",
)

EMOTION_MARKERS = (
    "чувствую",
    "эмоци",
    "страшно",
    "тревожно",
    "обидно",
    "стыдно",
    "ревную",
    "больно",
    "плохо",
    "грустно",
    "злюсь",
    "бесит",
    "одиноко",
    "накрывает",
    "нервно",
)

FANTASY_MARKERS = (
    "фантаз",
    "представь",
    "представим",
    "вообрази",
    "сценар",
    "если бы",
    "мечтаю",
    "роль",
    "как будто",
)

RESISTANCE_MARKERS = (
    "не хочу",
    "не готов",
    "не могу",
    "не буду",
    "не сейчас",
    "не надо",
    "стоп",
    "хватит",
    "сомневаюсь",
    "не уверен",
    "не верю",
)

CURIOSITY_MARKERS = (
    "почему",
    "зачем",
    "что если",
    "интересно",
    "любопытно",
    "как это",
    "как работает",
    "что значит",
    "в чем",
    "разбери",
    "теория",
)

EXPLICIT_REQUEST_MARKERS = (
    "скажи",
    "объясни",
    "покажи",
    "дай",
    "напиши",
    "составь",
    "распиши",
    "подскажи",
    "перепиши",
    "сделай",
    "помоги",
    "что делать",
    "как ответить",
    "что сказать",
    "какой выбрать",
    "нужен текст",
    "нужен план",
)

CONFUSION_MARKERS = (
    "не понимаю",
    "не понял",
    "не поняла",
    "в смысле",
    "неясно",
    "запутал",
    "запутала",
    "что ты имеешь в виду",
    "что это значит",
)

LIST_REQUEST_MARKERS = (
    "спис",
    "по пунктам",
    "пункт",
    "1.",
    "чеклист",
    "bullet",
    "list",
    "этап",
    "шаг",
)

BASE_REFLECTIONS = {
    "desire": "Тут у тебя уже не просто интерес, а притяжение.",
    "emotion": "Тут уже звучит чувство, а не просто мысль.",
    "fantasy": "Тебя цепляет не картинка сама по себе, а заряд внутри нее.",
    "resistance": "Ты сейчас скорее притормаживаешь, чем идешь дальше.",
    "curiosity": "Тебя цепляет не факт, а слой под ним.",
    "short_reply": "Ты оставил это приоткрытым.",
    "explicit_request": "Тебе нужен не общий разговор, а точное попадание.",
    "confusion": "Здесь что-то не щелкнуло до конца.",
}

PERSONALIZED_REFLECTIONS = {
    "desire": "По тому, как ты это подаешь, там уже есть твой личный крючок.",
    "emotion": "По твоему тону видно, что это задевает тебя глубже обычного.",
    "fantasy": "У тебя здесь цепляет не схема, а совсем личный внутренний заряд.",
    "curiosity": "Ты не просто спрашиваешь, а уже подбираешься к своему слою смысла.",
    "explicit_request": "Ты просишь прямо, но за запросом уже чувствуется твой приоритет.",
}

SOFT_REFLECTIONS = {
    "emotion": "Это у тебя уже звучит слишком живо, чтобы отмахнуться.",
    "resistance": "Ты сейчас держишь дистанцию не просто так.",
    "confusion": "Тут у тебя пока не сошлась какая-то важная часть.",
    "short_reply": "Ты оставил это коротко, но там явно не пусто.",
}

FOLLOWUP_QUESTIONS = {
    "desire": "Что там тянет тебя сильнее — близость, контроль или сам риск?",
    "emotion": "Что сейчас в этом громче — страх, злость или тяга все равно не отпускать?",
    "fantasy": "Что там для тебя важнее — контроль, внимание или нарушение рамки?",
    "resistance": "Что тебя держит сильнее — недоверие, страх последствий или то, что это просто не твой ритм?",
    "curiosity": "Тебе сейчас нужнее теория, живой сценарий или разбор именно про тебя?",
    "short_reply": "Что там на самом деле сильнее — интерес, сомнение или желание проверить границу?",
    "explicit_request": "Что для тебя тут важнее — быстрый ответ, чувство контроля или эффект на другого?",
    "confusion": "Что сейчас мешает больше — смысл, логика или ощущение, что это вообще не про тебя?",
}


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split()).strip()


def _normalize_with_breaks(text: str) -> str:
    return re.sub(r"[ \t]+", " ", str(text or "")).strip()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _is_short_reply(text: str) -> bool:
    words = [word for word in re.split(r"\s+", text) if word]
    return len(words) <= 3 and len(text) <= 24 and "?" not in text


def _is_high_engagement(state: dict | None) -> bool:
    snapshot = state or {}
    interest = float(snapshot.get("interest", 0.0) or 0.0)
    attraction = float(snapshot.get("attraction", 0.0) or 0.0)
    interaction_count = int(snapshot.get("interaction_count", 0) or 0)
    return interest >= 0.68 or attraction >= 0.5 or (interest + attraction >= 1.0 and interaction_count >= 5)


def _user_explicitly_requested_list(user_message: str) -> bool:
    normalized = _normalize(user_message)
    return _contains_any(normalized, LIST_REQUEST_MARKERS)


def _collapse_list_shape(text: str) -> str:
    collapsed = re.sub(r"(?:^|\s)(?:[-*•]|\d+[.)])\s+", " ", str(text or ""))
    if not LIST_MARKER_RE.search(text):
        return " ".join(collapsed.split()).strip()

    items = [
        re.sub(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip()
        for line in collapsed.splitlines()
        if line.strip()
    ]
    flattened = " ".join(item.rstrip(" ,;:-") for item in items if item)
    return " ".join(flattened.split()).strip()


def _trim_sentences(text: str, *, max_sentences: int) -> str:
    if not text:
        return text
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return " ".join(parts[:max_sentences]).strip()


def _limit_questions(text: str) -> str:
    if text.count("?") <= 1:
        return text
    first_index = text.find("?")
    return text[: first_index + 1] + text[first_index + 1 :].replace("?", ".")


def _extract_question(text: str) -> str:
    for part in re.split(r"(?<=[.!?])\s+", text):
        candidate = part.strip()
        if candidate.endswith("?"):
            return candidate
    return ""


def _append_sentence(text: str, sentence: str) -> str:
    body = str(text or "").strip()
    addition = str(sentence or "").strip()
    if not addition:
        return body
    if not body:
        return addition
    if body[-1] not in ".!?":
        body += "."
    return f"{body} {addition}".strip()
