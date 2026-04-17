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
LOW_VALUE_OPENERS = (
    "Понимаю, что это может быть непросто.",
    "Это вполне естественно.",
    "Это хороший подход.",
    "Хорошо, давай попробуем рассмотреть это.",
    "Поняла.",
    "Понимаю.",
)
GENERIC_TRAILING_QUESTIONS = (
    "Как ты на это смотришь?",
    "Что ты думаешь об этом?",
    "Что думаешь?",
    "Как тебе такая идея?",
    "Как тебе такой вариант?",
    "Как тебе такой подход?",
)
META_SCRIPT_OPENERS = (
    "Вот что можно сказать:",
    "Вот несколько тем для разговора:",
    "Вот примерный текст:",
    "Вот план для обсуждения:",
    "Понял. Вот что можно сказать:",
    "Понял. Вот примерный текст:",
)
META_CLOSERS = (
    "Таким образом, вы сможете открыто обсудить все аспекты и лучше понять друг друга.",
    "Так будет проще и яснее.",
)
HOOK_LOW_VALUE_SENTENCE_MARKERS = (
    "это зависит от контекста",
    "сначала стоит",
    "иногда лучше не спешить",
    "в любом случае важно",
    "в любом случае решение",
    "разобрать всё по шагам",
)

HARD_REJECTION_OPENERS = (
    "Нет.",
    "Нет",
    "Я не буду это расписывать.",
    "Такой сценарий я тебе расписывать не буду.",
    "Я не стану это описывать.",
)

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


def _strip_meta_script_openers(text: str) -> str:
    guarded = text.strip()
    for opener in META_SCRIPT_OPENERS:
        if guarded.startswith(opener):
            guarded = guarded[len(opener):].strip()
            break
    return guarded


def _strip_meta_closers(text: str) -> str:
    guarded = text.strip()
    for closer in META_CLOSERS:
        if guarded.endswith(closer):
            guarded = guarded[: -len(closer)].rstrip(" ,;:-")
            break
    return guarded


def _unquote_numbered_list_items(text: str) -> str:
    return re.sub(r'(\d+[.)]\s+)"([^"\n]+)"', r"\1\2", text)


def _looks_like_risky_scene_lecture(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False

    sentences = [part for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]
    lowered = normalized.lower()
    lecture_markers = (
        "\u0432\u0430\u0436\u043d\u043e",
        "\u0437\u0430\u0440\u0430\u043d\u0435\u0435",
        "\u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e",
        "\u0441\u043d\u0430\u0447\u0430\u043b\u0430",
        "\u043f\u043e\u0442\u043e\u043c",
        "\u043d\u0438\u043a\u0430\u043a\u0438\u0445",
        "\u0441\u0442\u043e\u043f",
        "\u043f\u0440\u0435\u0437\u0435\u0440\u0432",
        "\u0437\u0430\u0449\u0438\u0442",
        "\u0442\u0440\u0435\u0437\u0432",
        "\u0434\u043e\u0433\u043e\u0432\u043e\u0440",
        "\u043f\u0440\u0430\u0432\u0438\u043b",
    )
    marker_hits = sum(1 for marker in lecture_markers if marker in lowered)
    has_list_shape = bool(re.search(r"(?:^|\s)(?:\d+[.)]|[-•])\s", normalized))
    return len(normalized) > 420 or len(sentences) > 5 or marker_hits >= 4 or has_list_shape


def _compress_risky_scene_lecture(text: str, *, user_message: str = "") -> str:
    lowered = " ".join(str(text or "").lower().split())
    request = " ".join(str(user_message or "").lower().split())
    drug_markers = (
        "\u043d\u0430\u0440\u043a\u043e\u0442",
        "\u043c\u0435\u0444",
        "\u043a\u043e\u043a\u0441",
        "2cb",
        "2-cb",
        "\u043f\u043e\u0434 \u043a\u0430\u0439\u0444",
        "\u043f\u043e\u0434 \u0432\u0435\u0449\u0435\u0441\u0442\u0432",
    )
    barrier_markers = (
        "\u0431\u0435\u0437 \u043f\u0440\u0435\u0437\u0435\u0440\u0432",
        "\u0431\u0435\u0437 \u0437\u0430\u0449\u0438\u0442",
    )
    has_drugs = any(marker in lowered for marker in drug_markers)
    has_no_barrier = any(marker in lowered for marker in barrier_markers)

    if "\u0445\u0438\u043c" in request and has_drugs:
        opener = "Тут тебя тянет уже не к накалу, а к сносу контроля."
    elif any(marker in request for marker in ("\u043e\u0440\u0433", "\u0432\u0442\u0440\u043e\u0435\u043c", "\u0432\u0447\u0435\u0442\u0432\u0435\u0440\u043e\u043c")):
        opener = "Так легко собрать не напряжение, а хаос."
    else:
        opener = "Так ты это только собьёшь."
    middle_parts = []
    if has_drugs:
        middle_parts.append(
            "В изменённом состоянии там получается не острота, а мутность."
        )
    if has_no_barrier:
        middle_parts.append(
            "Когда пропадают базовые рамки, там уже не искра, а общий риск для всех."
        )
    if not middle_parts:
        middle_parts.append(
            "Если рамка плывёт, такой заход разваливается быстрее, чем успевает разогреться."
        )
    middle = " ".join(middle_parts)

    if "\u0445\u0438\u043c" in request:
        closer = (
            "Если хочешь, я лучше соберу чистую версию того же накала — без сноса рамки и мутности. "
            "Тебя тут тянет к самому изменённому состоянию или к ощущению, что контроль исчезает?"
        )
    else:
        closer = (
            "Если хочешь, я лучше соберу соседнюю версию того же напряжения — чище, плотнее и без развала в хаос. "
            "Тебя здесь сильнее тянет к новизне, к ощущению сдвига границ или к самой потере контроля?"
        )
    return f"{opener} {middle} {closer}"


def _compress_charged_probe_lecture(text: str, *, user_message: str = "") -> str:
    request = " ".join(str(user_message or "").lower().split())
    if any(marker in request for marker in ("втроем", "тройнич", "группов", "оргия", "секс", "жмж", "мжм", "ммж", "мжмж")):
        opener = (
            "Нормальный заряженный запрос. Обычно там цепляет не буквальная механика, а перекос внимания, новизна и ощущение сдвига."
            if "хочу" in request
            else "В таких фантазиях обычно работает не схема, а перекос внимания, риск и ощущение, что воздух стал плотнее."
        )
        return (
            f"{opener} Одних в этом тянет зрелище, других — ревность, давление или сам сдвиг границ. "
            "Тебя здесь сильнее цепляет новизна, ревность или именно ощущение, что рамка начинает плыть?"
        )
    return (
        "Тут обычно цепляет не буквальная схема, а то, как меняется напряжение между людьми. "
        "Когда ответ превращается в инструктаж, магия умирает. "
        "Тебя здесь что на самом деле заводит сильнее всего?"
    )


def _compress_to_dialogue_turn(text: str, *, max_sentences: int = 2, max_chars: int = 260) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return normalized

    raw_sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]
    sentences = [
        sentence
        for sentence in raw_sentences
        if not any(marker in sentence.lower() for marker in HOOK_LOW_VALUE_SENTENCE_MARKERS)
    ]
    if not sentences:
        return ""

    compact = " ".join(sentences[:max_sentences]).strip()
    if len(compact) <= max_chars:
        return compact

    clipped = compact[:max_chars].rstrip(" ,;:-")
    last_break = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if last_break >= int(max_chars * 0.6):
        clipped = clipped[: last_break + 1]
    else:
        last_space = clipped.rfind(" ")
        if last_space >= int(max_chars * 0.6):
            clipped = clipped[:last_space]
    return clipped.rstrip(" ,;:-") + ("." if clipped and clipped[-1] not in ".!?" else "")


def _build_dialogue_turn_fallback(user_message: str) -> str:
    topic = _classify_hook_topic(user_message)
    if topic == "support":
        return "Похоже, это правда давит и цепляет по-настоящему, без «правильного ответа»."
    if topic == "pricing":
        return "Цена тут редко решает в одиночку, если ценность бьёт сразу."
    if topic == "offer":
        return "Оффер держится не на полноте, а на том, насколько быстро он попадает в нерв."
    if topic == "hiring":
        return "По людям обычно всё решает не таблица, а хочется ли тебе усиливать именно этого человека."
    if topic == "design":
        return "У такого экрана всё держится на первом ударе, а не на аккуратном объяснении."
    if topic == "tone":
        return "Тон держится не на вежливости, а на том, чувствуется ли в нём нерв."
    if topic == "timing":
        return "По времени обычно видно одно: момент уже пришёл или ты пока только тянешь паузу."
    if topic == "diagnostic":
        return "Обычно там ломается не одна мелочь, а сам первый импульс."
    if topic == "simplification":
        return "Упростить стоит только там, где это усиливает удар, а не сушит идею."
    if topic == "energy":
        return "Энергия обычно умирает не от нехватки деталей, а от слишком ровной подачи."
    if topic == "approach":
        return "Заход живёт, пока в нём чувствуется направление, а не просто аккуратность."
    if topic == "go_no_go":
        return "Тут решает не длинная раскладка, а где у тебя настоящее да."
    if topic == "comparison":
        return "Тут важнее живой перекос между вариантами, чем аккуратная теория."
    return "Тут важнее живой отклик, чем безопасная раскладка."


def _classify_hook_topic(user_message: str) -> str:
    request = " ".join(str(user_message or "").lower().split())
    if not request:
        return "generic"

    if "цепляет" in request and not any(
        marker in request
        for marker in (
            "оффер",
            "лендинг",
            "экран",
            "прода",
            "конвер",
            "цена",
            "цену",
            "ценность",
            "paywall",
            "чек",
        )
    ):
        return "support"

    # In personal distress contexts ("всё цепляет", grief, family health) product-y topic pulls
    # ("оффер", "первый импульс", etc.) sound alien and can break trust.
    distress_markers = (
        "мне плохо",
        "мне тяжело",
        "ничего не радует",
        "не радует",
        "не хочу",
        "пусто",
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
        "ритм",
        "давлен",
        "боль в груди",
        "одышк",
        "обморок",
        "врач",
        "скорая",
        "муж",
        "мама",
        "папа",
        "ребен",
        "ребён",
        "собак",
        "питом",
    )
    if any(marker in request for marker in distress_markers):
        return "support"

    if any(marker in request for marker in ("цена", "цену", "ценность", "дорого", "paywall", "деньги", "чек")):
        return "pricing"
    if "оффер" in request:
        return "offer"
    if any(marker in request for marker in ("в команду", "этого человека", "нанимать", "кандидат")):
        return "hiring"
    if any(marker in request for marker in ("лендинг", "экран", "первый экран", "выглядит", "дешево", "дёшево")):
        return "design"
    if any(marker in request for marker in ("тон", "звучит", "сухо", "жёстче", "смягчить")):
        return "tone"
    if any(marker in request for marker in ("сейчас", "подождать", "пушить", "рано")):
        return "timing"
    # "цепляет" in human talk often means "болит/задевает", not product diagnostics.
    if any(marker in request for marker in ("почему", "не продаётся", "слабое место", "мертво")):
        return "diagnostic"
    if "проще" in request:
        return "simplification"
    if "энергия" in request or "пусто" in request:
        return "energy"
    if "заход" in request:
        return "approach"
    if any(marker in request for marker in ("запускать", "жизнеспособно", "дожимать", "стоит ли", "брать", "отпустить")):
        return "go_no_go"
    if "или" in request:
        return "comparison"
    if any(marker in request for marker in ("как тебе", "что скажешь")):
        return "taste"
    return "generic"


def _build_dialogue_pull_question(user_message: str) -> str:
    request = " ".join(str(user_message or "").lower().split())
    if not request:
        return ""

    topic = _classify_hook_topic(user_message)
    if topic == "support":
        if any(marker in request for marker in ("дальше", "что делать", "куда", "как быть")):
            return "С чего начнём — с самого срочного или с того, что даст тебе хоть 10% легче прямо сейчас?"
        if any(marker in request for marker in ("ничего", "не радует", "пусто")):
            return "Это больше похоже на усталость, тревогу или чувство пустоты?"
        return "Что сейчас давит сильнее — горе, тревога за близких или усталость от решений?"
    if "хим" in request:
        return "Тебя здесь сильнее тянет к изменённому состоянию или к ощущению, что рамка исчезает?"
    if any(marker in request for marker in ("орг", "втроем", "вчетвером", "секс", "жмж", "мжм", "ммж", "мжмж", "тройнич", "группов")):
        return "Тебя здесь сильнее цепляет новизна, ревность или сам сдвиг границ?"
    if topic == "pricing":
        return "Тебя тут сильнее тормозит сам чек, ощущение слабой ценности или страх, что рано просишь деньги?"
    if topic == "offer":
        return "У тебя тут сейчас проседает сила обещания, ясность или ощущение ценности?"
    if topic == "hiring":
        return "Тебя в этом человеке смущает слабость, темп или просто ощущение, что вы не совпадёте?"
    if topic == "design":
        return "У тебя тут проседает удар, ясность или доверие с первого экрана?"
    if topic == "tone":
        return "Ты хочешь звучать здесь жёстче, теплее или просто дороже?"
    if topic == "timing":
        return "Тебя тут держит реальный риск или просто желание ещё немного потянуть паузу?"
    if topic == "diagnostic":
        return "У тебя тут проседает оффер, доверие или само желание нажать дальше?"
    if topic == "simplification":
        return "Ты хочешь здесь убрать лишнее или боишься срезать сам нерв?"
    if topic == "energy":
        return "У тебя тут не хватает удара, контраста или просто живого желания продолжать?"
    if topic == "approach":
        return "Тебя в этом заходе цепляет сам угол, подача или обещание результата?"
    if topic == "go_no_go":
        return "Тебя сюда тянет по делу или больше пугает мысль упустить момент?"
    if topic == "comparison":
        return "Что тебе самому тут ближе из этих двух вариантов?"
    if topic == "taste":
        return "Тебя тут больше цепляет форма, энергия или сам заход?"
    if "что ты думаешь" in request or "что думаешь" in request:
        return "А тебя в этом что цепляет сильнее всего?"
    return "А тебя в этом что цепляет сильнее всего?"


def apply_human_style_guardrails(
    text: str,
    *,
    answer_first: bool,
    allow_follow_up_question: bool,
    strip_meta_framing: bool = False,
    soften_hard_rejection: bool = False,
    compress_risky_scene_lecture: bool = False,
    compress_charged_probe_lecture: bool = False,
    compress_to_dialogue_turn: bool = False,
    prefer_follow_up_question: bool = False,
    user_message: str = "",
    hook_max_sentences: int = 2,
    hook_max_chars: int = 260,
    topic_questions_enabled: bool = True,
) -> str:
    guarded = " ".join(str(text or "").split()).strip()
    if not guarded:
        return guarded

    if answer_first:
        for opener in LOW_VALUE_OPENERS:
            prefix = opener + " "
            if guarded.startswith(prefix):
                guarded = guarded[len(prefix):].strip()
                break

    if strip_meta_framing:
        guarded = _strip_meta_script_openers(guarded)
        guarded = _strip_meta_closers(guarded)
        guarded = _unquote_numbered_list_items(guarded)

    if soften_hard_rejection:
        for opener in HARD_REJECTION_OPENERS:
            if guarded.startswith(opener):
                guarded = guarded[len(opener):].lstrip(" ,.;:-")
                break
        if guarded.startswith("Такой сценарий"):
            guarded = "Так это только испортит сцену. " + guarded
        elif guarded.startswith("Я тебе это расписывать не буду"):
            guarded = guarded.replace(
                "Я тебе это расписывать не буду",
                "Так это только испортит момент",
                1,
            )

    if compress_risky_scene_lecture:
        guarded = _compress_risky_scene_lecture(guarded, user_message=user_message)

    if compress_charged_probe_lecture:
        guarded = _compress_charged_probe_lecture(guarded, user_message=user_message)

    if compress_to_dialogue_turn:
        guarded = _compress_to_dialogue_turn(
            guarded,
            max_sentences=max(1, int(hook_max_sentences or 2)),
            max_chars=max(120, int(hook_max_chars or 260)),
        )
        if not guarded:
            guarded = _build_dialogue_turn_fallback(user_message)

    if answer_first and not allow_follow_up_question:
        for question in GENERIC_TRAILING_QUESTIONS:
            suffix = " " + question
            if guarded.endswith(suffix):
                guarded = guarded[: -len(suffix)].rstrip(" ,;:-")
                if guarded and guarded[-1] not in ".!?":
                    guarded += "."
                break

    if not allow_follow_up_question and guarded.count("?") > 1 and not strip_meta_framing:
        first_index = guarded.find("?")
        guarded = guarded[: first_index + 1] + guarded[first_index + 1 :].replace("?", ".")

    if prefer_follow_up_question and "?" not in guarded:
        question = _build_dialogue_pull_question(user_message) if topic_questions_enabled else ""
        if question:
            if guarded and guarded[-1] not in ".!?":
                guarded += "."
            guarded = f"{guarded} {question}".strip()

    return guarded.strip()


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
