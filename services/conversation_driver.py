from __future__ import annotations

import re
from typing import Any

from services.response_guardrails import detect_crisis_signal


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
DRIVER_STAGES = {"start", "warmup", "trust", "deep"}
HEAVY_TONES = {"overwhelmed", "anxious", "guarded"}
OPEN_LOOP_MARKERS = (
    "это только часть",
    "не вся картина",
    "тут еще есть слой",
    "здесь все меняется",
)
LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")

QUESTION_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "q01",
        "intent": "desire",
        "stages": ("start",),
        "text": "Что здесь важнее — результат или сам путь к нему?",
    },
    {
        "id": "q02",
        "intent": "desire",
        "stages": ("warmup",),
        "text": "В этом больше импульса попробовать или ощущения, что это давно назрело?",
    },
    {
        "id": "q03",
        "intent": "desire",
        "stages": ("trust", "deep"),
        "text": "Если убрать чужие ожидания, ты бы выбрал это так же уверенно или уже начал бы сомневаться?",
    },
    {
        "id": "q04",
        "intent": "emotion",
        "stages": ("start",),
        "text": "Что здесь сейчас звучит громче — тревога, обида или надежда?",
    },
    {
        "id": "q05",
        "intent": "emotion",
        "stages": ("warmup",),
        "text": "Что сильнее задевает — сам факт, тон или то, что это меняет всю картину?",
    },
    {
        "id": "q06",
        "intent": "emotion",
        "stages": ("trust", "deep"),
        "text": "Если назвать это честно, это больше про страх потерять, злость не быть услышанным или усталость тащить всё самому?",
    },
    {
        "id": "q07",
        "intent": "fantasy",
        "stages": ("start",),
        "text": "В этой идее тебя держит свобода, масштаб или новая роль?",
    },
    {
        "id": "q08",
        "intent": "fantasy",
        "stages": ("warmup",),
        "text": "Если представить это без ограничений, тебе важнее влияние, признание или ощущение движения?",
    },
    {
        "id": "q09",
        "intent": "fantasy",
        "stages": ("trust", "deep"),
        "text": "Для тебя это скорее шанс вырасти, право быть другим или попытка вернуть себе контроль?",
    },
    {
        "id": "q10",
        "intent": "resistance",
        "stages": ("start",),
        "text": "Что стопорит сильнее — сомнение в себе или сомнение в самой идее?",
    },
    {
        "id": "q11",
        "intent": "resistance",
        "stages": ("warmup",),
        "text": "Ты тормозишь потому что рано, потому что не доверяешь или потому что цена кажется слишком высокой?",
    },
    {
        "id": "q12",
        "intent": "resistance",
        "stages": ("trust", "deep"),
        "text": "Если бы никто не оценивал тебя со стороны, ты бы всё ещё держал стоп или уже пошёл дальше?",
    },
    {
        "id": "q13",
        "intent": "curiosity",
        "stages": ("start",),
        "text": "Тебе сейчас нужнее понять механику, увидеть пример или примерить это на себя?",
    },
    {
        "id": "q14",
        "intent": "curiosity",
        "stages": ("warmup",),
        "text": "Ты хочешь разобраться в причине, в последствиях или в том, как этим управлять?",
    },
    {
        "id": "q15",
        "intent": "curiosity",
        "stages": ("trust", "deep"),
        "text": "Здесь больше вопрос «почему так» или «что это меняет лично для меня»?",
    },
    {
        "id": "q16",
        "intent": "short_reply",
        "stages": ("start",),
        "text": "Скажи на один слой глубже: там больше интерес, осторожность или внутреннее «а вдруг»?",
    },
    {
        "id": "q17",
        "intent": "short_reply",
        "stages": ("warmup", "trust"),
        "text": "Если развернуть это в одну мысль, ты сейчас скорее за, против или пока на пороге?",
    },
    {
        "id": "q18",
        "intent": "short_reply",
        "stages": ("deep",),
        "text": "Твоя короткость сейчас про ясность, усталость или нежелание назвать главное?",
    },
    {
        "id": "q19",
        "intent": "explicit_request",
        "stages": ("start",),
        "text": "Тебе нужен быстрый ответ, рабочая формулировка или способ не ошибиться?",
    },
    {
        "id": "q20",
        "intent": "explicit_request",
        "stages": ("warmup",),
        "text": "Ты хочешь решение под задачу, под человека или под свой стиль?",
    },
    {
        "id": "q21",
        "intent": "explicit_request",
        "stages": ("trust", "deep"),
        "text": "В ответе для тебя ценнее точность, влияние на другого или ощущение, что это звучит по-твоему?",
    },
    {
        "id": "q22",
        "intent": "confusion",
        "stages": ("start",),
        "text": "Что именно не сходится — смысл, шаги или зачем это вообще нужно?",
    },
    {
        "id": "q23",
        "intent": "confusion",
        "stages": ("warmup",),
        "text": "Тебе мешает формулировка, логика или то, что это не стыкуется с твоим опытом?",
    },
    {
        "id": "q24",
        "intent": "confusion",
        "stages": ("trust", "deep"),
        "text": "Если убрать лишнее, где узел — в фактах, в интерпретации или в твоём отношении к этому?",
    },
    {
        "id": "q25",
        "intent": "any",
        "stages": ("start", "warmup", "trust", "deep"),
        "text": "Тебе сейчас важнее ясность, движение или ощущение, что это действительно твой выбор?",
    },
)

DESIRE_MARKERS = (
    "хочу",
    "хочется",
    "тянет",
    "цепляет",
    "манит",
    "привлекает",
    "нравится",
    "назрело",
)
EMOTION_MARKERS = (
    "чувствую",
    "тревожно",
    "обидно",
    "задел",
    "задело",
    "задевает",
    "злит",
    "злость",
    "больно",
    "надежда",
    "устал",
    "страшно",
)
FANTASY_MARKERS = (
    "представь",
    "представим",
    "если представить",
    "если бы",
    "идея",
    "роль",
    "сценарий",
    "мечтаю",
)
RESISTANCE_MARKERS = (
    "не хочу",
    "не могу",
    "не готов",
    "стоп",
    "торможу",
    "сомневаюсь",
    "не доверяю",
    "рано",
)
CURIOSITY_MARKERS = (
    "почему",
    "зачем",
    "как это",
    "как этим",
    "что значит",
    "интересно",
    "любопытно",
    "разобраться",
    "механика",
)
EXPLICIT_REQUEST_MARKERS = (
    "скажи",
    "дай",
    "объясни",
    "напиши",
    "составь",
    "распиши",
    "подскажи",
    "просто ответь",
    "по делу",
    "про меня",
    "про себя",
    "разбор",
    "живой сценарий",
)
CONFUSION_MARKERS = (
    "не понимаю",
    "не понял",
    "не поняла",
    "не сходится",
    "неясно",
    "запутался",
    "запуталась",
    "что ты имеешь в виду",
)
FULL_REVEAL_MARKERS = (
    "дай полный ответ",
    "скажи прямо",
    "без вопросов",
    "не раскручивай",
    "просто ответь",
    "просто скажи всё",
    "сразу по делу",
)
UNSAFE_CONTEXT_MARKERS = (
    "суицид",
    "убить",
    "оруж",
    "бомб",
    "наркот",
    "меф",
    "2cb",
    "2-cb",
    "секс",
    "оргия",
)

SENSITIVE_SUPPORT_MARKERS = (
    "смерт",
    "умер",
    "умерла",
    "умерли",
    "не стало",
    "потер",
    "похорон",
    "пансионат",
    "сердц",
    "аритм",
    "нарушение ритма",
    "боль в груди",
    "одышк",
    "обморок",
    "врач",
    "скорая",
)
LIST_REQUEST_MARKERS = (
    "спис",
    "по пунктам",
    "чеклист",
    "bullet",
    "list",
    "шаг",
)
FULL_REVEAL_MARKERS += (
    "дай полный ответ",
    "скажи прямо",
    "без вопросов",
    "не раскручивай",
    "просто ответь",
    "просто скажи всё",
    "сразу по делу",
    "без уточнений",
)
LIST_REQUEST_MARKERS += (
    "спис",
    "по пунктам",
    "чеклист",
    "шаг",
)

BASE_REFLECTIONS = {
    "desire": "Тут у тебя уже не просто интерес, а явное притяжение.",
    "emotion": "Здесь уже звучит чувство, а не просто оценка ситуации.",
    "fantasy": "Тебя держит не только сама идея, но и то, что она обещает внутри.",
    "resistance": "Ты здесь скорее притормаживаешь, чем действительно отпускаешь тему.",
    "curiosity": "Тут важен не только факт, а слой под ним.",
    "short_reply": "Ты оставил это коротко, но не пусто.",
    "explicit_request": "Тебе нужен не общий разговор, а точное попадание в задачу.",
    "confusion": "Здесь у тебя пока не сходится какая-то ключевая часть.",
}
SOFT_REFLECTIONS = {
    "emotion": "Это у тебя сейчас звучит слишком живо, чтобы пройти мимо.",
    "resistance": "Ты держишь паузу не просто так.",
    "confusion": "Похоже, тут пока не сложился основной смысловой узел.",
    "short_reply": "Ты ответил коротко, но главное там явно не названо.",
}
DEEP_REFLECTIONS = {
    "desire": "По тому, как ты это держишь, там уже есть личный выбор, а не случайный импульс.",
    "emotion": "По тону видно, что это задевает глубже, чем кажется снаружи.",
    "fantasy": "Для тебя это уже не абстрактная идея, а способ сдвинуть внутреннюю рамку.",
    "curiosity": "Ты уже не просто спрашиваешь, а подбираешься к личному смыслу этого хода.",
    "explicit_request": "За запросом слышно, что тебе важна не только польза, но и точное ощущение своего ответа.",
}


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
    reflection = build_reflection(intent, state)
    if _question_limit_reached(state):
        return reflection
    question = select_followup_question(intent, resolve_driver_stage(state), state)
    return f"{reflection} {question}".strip()


def resolve_driver_stage(state: dict) -> str:
    snapshot = state or {}
    phase = str(snapshot.get("conversation_phase") or "").strip().lower()
    if phase in DRIVER_STAGES:
        return phase

    interaction_count = int(snapshot.get("interaction_count", 0) or 0)
    if interaction_count >= 20:
        return "deep"
    if interaction_count >= 8:
        return "trust"
    if interaction_count >= 3:
        return "warmup"
    return "start"


def wants_full_reveal(message: str) -> bool:
    return _contains_any(_normalize(message), FULL_REVEAL_MARKERS)


def is_driver_safe_context(message: str, state: dict | None = None) -> bool:
    normalized = _normalize(message)
    if not normalized:
        return False
    if detect_crisis_signal(message) is not None:
        return False
    # When the user is in acute grief / caregiving / medical stress, "driver" probing
    # questions tend to sound tone-deaf. Let the base system prompt handle support.
    if _contains_any(normalized, SENSITIVE_SUPPORT_MARKERS):
        return False
    if _contains_any(normalized, UNSAFE_CONTEXT_MARKERS):
        return False
    if str((state or {}).get("safety_lock") or "").strip().lower() == "driver_off":
        return False
    return True


def select_followup_question(intent: str, stage: str, state: dict) -> str:
    return str(_select_question_entry(intent, stage, state)["text"])


def build_reflection(intent: str, state: dict) -> str:
    normalized_intent = _normalize_intent(intent)
    stage = resolve_driver_stage(state)
    emotional_tone = str((state or {}).get("emotional_tone") or "").strip().lower()
    if emotional_tone in HEAVY_TONES:
        return SOFT_REFLECTIONS.get(normalized_intent, BASE_REFLECTIONS.get(normalized_intent, BASE_REFLECTIONS["curiosity"]))
    if stage in {"trust", "deep"}:
        return DEEP_REFLECTIONS.get(normalized_intent, BASE_REFLECTIONS.get(normalized_intent, BASE_REFLECTIONS["curiosity"]))
    return BASE_REFLECTIONS.get(normalized_intent, BASE_REFLECTIONS["curiosity"])


def resolve_followup_entry(intent: str, state: dict) -> dict[str, Any]:
    return dict(_select_question_entry(intent, resolve_driver_stage(state), state))


def apply_driver_guardrails(
    text: str,
    *,
    user_message: str,
    state: dict | None = None,
    intent: str | None = None,
    followup_question: str | None = None,
) -> str:
    snapshot = state or {}
    resolved_intent = intent or detect_intent(user_message)
    fallback = build_followup(resolved_intent, snapshot)
    normalized = _normalize_with_breaks(text)
    if not normalized:
        return fallback

    full_reveal_requested = wants_full_reveal(user_message)

    if not _user_explicitly_requested_list(user_message):
        normalized = _collapse_list_shape(normalized)

    normalized = _trim_sentences(normalized, max_sentences=3)
    normalized = _limit_questions(normalized)
    if not normalized:
        return fallback

    question_limit_reached = _question_limit_reached(snapshot)
    if "?" not in normalized and not question_limit_reached and not full_reveal_requested:
        question = str(followup_question or _extract_question(fallback)).strip()
        normalized = _append_sentence(normalized, question)

    normalized = _trim_sentences(normalized, max_sentences=3)
    normalized = _normalize_with_breaks(normalized)
    if (
        not question_limit_reached
        and not full_reveal_requested
        and not normalized.endswith("?")
        and not any(marker in normalized.lower() for marker in OPEN_LOOP_MARKERS)
    ):
        question = str(followup_question or _extract_question(fallback)).strip()
        normalized = _append_sentence(normalized, question)
        normalized = _trim_sentences(normalized, max_sentences=3)
    return normalized.strip()


def _select_question_entry(intent: str, stage: str, state: dict) -> dict[str, Any]:
    normalized_intent = _normalize_intent(intent)
    resolved_stage = stage if stage in DRIVER_STAGES else resolve_driver_stage(state)
    emotional_tone = str((state or {}).get("emotional_tone") or "").strip().lower()
    last_question_id = str((state or {}).get("last_driver_question_id") or "").strip()

    stage_sequence = [resolved_stage]
    if emotional_tone in HEAVY_TONES and resolved_stage != "start":
        stage_sequence.insert(0, "start")

    candidates: list[dict[str, Any]] = []
    for candidate_stage in stage_sequence:
        candidates = _questions_for(normalized_intent, candidate_stage)
        if candidates:
            break
    if not candidates:
        candidates = _questions_for("any", resolved_stage)
    if not candidates and emotional_tone in HEAVY_TONES:
        candidates = _questions_for("any", "start")
    if not candidates:
        candidates = [dict(QUESTION_BANK[-1])]

    filtered_candidates = [entry for entry in candidates if str(entry["id"]) != last_question_id]
    if filtered_candidates:
        return dict(filtered_candidates[_candidate_index(state, filtered_candidates)])

    fallback_candidates = [
        entry
        for entry in QUESTION_BANK
        if resolved_stage in entry["stages"] and str(entry["id"]) != last_question_id
    ]
    if fallback_candidates:
        return dict(fallback_candidates[_candidate_index(state, fallback_candidates)])

    any_candidates = [entry for entry in QUESTION_BANK if entry["intent"] == "any"]
    if any_candidates:
        return dict(any_candidates[0])
    return dict(QUESTION_BANK[-1])


def _questions_for(intent: str, stage: str) -> list[dict[str, Any]]:
    return [
        dict(entry)
        for entry in QUESTION_BANK
        if str(entry["intent"]) == intent and stage in tuple(entry["stages"])
    ]


def _candidate_index(state: dict | None, candidates: list[dict[str, Any]]) -> int:
    if not candidates:
        return 0
    snapshot = state or {}
    interaction_count = int(snapshot.get("interaction_count", 0) or 0)
    interest = int(float(snapshot.get("interest", 0.0) or 0.0) * 100)
    return (interaction_count + interest) % len(candidates)


def _question_limit_reached(state: dict | None) -> bool:
    snapshot = state or {}
    return int(snapshot.get("driver_question_streak", 0) or 0) >= 2


def _normalize_intent(intent: str) -> str:
    normalized = str(intent or "curiosity").strip().lower()
    return normalized if normalized in INTENTS else "curiosity"


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split()).strip()


def _normalize_with_breaks(text: str) -> str:
    return re.sub(r"[ \t]+", " ", str(text or "")).strip()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _is_short_reply(text: str) -> bool:
    words = [word for word in re.split(r"\s+", text) if word]
    return len(words) <= 3 and len(text) <= 24 and "?" not in text


def _user_explicitly_requested_list(user_message: str) -> bool:
    return _contains_any(_normalize(user_message), LIST_REQUEST_MARKERS)


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
