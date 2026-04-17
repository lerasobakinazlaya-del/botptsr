from __future__ import annotations

import re


HOOK_LIBRARY: dict[str, tuple[str, ...]] = {
    "curiosity_hooks": (
        "и здесь есть деталь, которую обычно замечают не сразу",
        "но самое интересное тут чуть глубже",
        "и именно это обычно меняет весь тон дальше",
        "но тут все решает один тихий нюанс",
        "и в этом месте картина только начинает раскрываться",
        "но главное здесь не лежит на поверхности",
    ),
    "tension_hooks": (
        "и именно здесь все обычно начинает смещаться",
        "но дальше это может повернуть совсем по-разному",
        "и вот в этой точке все становится острее",
        "но именно тут обычно появляется настоящий сдвиг",
        "и дальше многое зависит от того, как ты это поведешь",
        "но в этой части все держится не так ровно, как кажется",
    ),
    "partial_reveal_hooks": (
        "но это пока только верхний слой",
        "и это еще не вся картина",
        "но главный поворот тут еще впереди",
        "и за этим есть слой поглубже",
        "но самая важная часть пока остается за кадром",
        "и тут как раз начинается то, что снаружи не видно",
    ),
    "escalation_hooks": (
        "и дальше это может зайти глубже, чем кажется сейчас",
        "но на этом это обычно не останавливается",
        "и это только точка, где все начинает набирать силу",
        "но дальше у этого разговора может появиться совсем другой вес",
        "и дальше можно аккуратно прояснить один важный узел",
        "и дальше мы можем идти маленькими шагами, без давления",
    ),
    "personalization_hooks": (
        "и с тобой это может сработать совсем не так, как с другими",
        "но в твоем случае все упирается в один личный нюанс",
        "и для тебя здесь может открыться совсем другой ход",
        "но по тому, как ты это подаешь, у тебя тут своя траектория",
        "и именно у тебя здесь может быть другая глубина",
        "но по твоему тону тут чувствуется совсем отдельная линия",
    ),
}

OPEN_LOOP_MARKERS = (
    "не вся картина",
    "только верхний слой",
    "главный поворот",
    "слой поглубже",
    "не лежит на поверхности",
    "только начинает",
    "зависит от того",
    "может повернуть",
    "может зайти глубже",
    "может появиться",
)

HEAVY_TONES = {"overwhelmed", "anxious", "guarded"}
PHASE_ORDER = {"start": 0, "warmup": 1, "trust": 2, "deep": 3}


def select_hook(state: dict, strategy: str) -> str:
    normalized_strategy = str(strategy or "auto").strip().lower()
    category = _resolve_category(state or {}, normalized_strategy)
    pool = list(HOOK_LIBRARY.get(category, ()))
    if not pool:
        return ""

    last_hook = str((state or {}).get("last_hook") or "").strip()
    if last_hook:
        filtered_pool = [hook for hook in pool if hook != last_hook]
        if filtered_pool:
            pool = filtered_pool

    seed = _build_seed(state or {}, normalized_strategy)
    return pool[seed % len(pool)]


def inject_hook(text: str, hook: str) -> str:
    normalized = _normalize_text(text)
    hook = str(hook or "").strip()
    if not normalized or not hook:
        return normalized
    if hook.lower() in normalized.lower():
        return normalized
    if normalized.endswith("?"):
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]
        if len(sentences) > 1:
            for index in range(len(sentences) - 1, -1, -1):
                if not sentences[index].endswith("?"):
                    sentences[index] = _merge_hook(sentences[index], hook)
                    return " ".join(sentences)
        return _merge_hook(normalized, hook)

    return _merge_hook(normalized, hook)


def ensure_open_loop(text: str) -> str:
    normalized = _trim_sentences(_normalize_text(text), max_sentences=5)
    if not normalized:
        return normalized
    if normalized.endswith("?"):
        return normalized

    lowered = normalized.lower()
    if any(marker in lowered for marker in OPEN_LOOP_MARKERS):
        return _ensure_terminal_punctuation(normalized)

    trailing = normalized[-1] if normalized[-1] in ".!?" else ""
    body = normalized[:-1].rstrip() if trailing else normalized
    if not body:
        return normalized
    return f"{body}. Если хочешь, продолжим."


def _resolve_category(state: dict, strategy: str) -> str:
    if strategy in HOOK_LIBRARY:
        return strategy

    emotional_tone = str(state.get("emotional_tone") or "neutral")
    if emotional_tone in HEAVY_TONES:
        return "curiosity_hooks"

    if strategy == "reengagement":
        if _is_high_engagement(state):
            return "personalization_hooks"
        if _phase_rank(state) >= PHASE_ORDER["trust"]:
            return "partial_reveal_hooks"
        return "curiosity_hooks"

    if _is_high_engagement(state):
        return "personalization_hooks"

    phase_rank = _phase_rank(state)
    interaction_count = int(state.get("interaction_count", 0) or 0)

    if phase_rank <= PHASE_ORDER["start"]:
        return "curiosity_hooks"
    if phase_rank < PHASE_ORDER["deep"]:
        return "tension_hooks" if interaction_count % 2 else "partial_reveal_hooks"
    return "escalation_hooks"


def _is_high_engagement(state: dict) -> bool:
    interest = float(state.get("interest", 0.0) or 0.0)
    attraction = float(state.get("attraction", 0.0) or 0.0)
    interaction_count = int(state.get("interaction_count", 0) or 0)
    return interest >= 0.72 or attraction >= 0.55 or (interest + attraction >= 1.1 and interaction_count >= 6)


def _phase_rank(state: dict) -> int:
    phase = str(state.get("conversation_phase") or "").strip().lower()
    if phase in PHASE_ORDER:
        return PHASE_ORDER[phase]

    interaction_count = int(state.get("interaction_count", 0) or 0)
    if interaction_count >= 20:
        return PHASE_ORDER["deep"]
    if interaction_count >= 8:
        return PHASE_ORDER["trust"]
    if interaction_count >= 3:
        return PHASE_ORDER["warmup"]
    return PHASE_ORDER["start"]


def _build_seed(state: dict, strategy: str) -> int:
    interaction_count = int(state.get("interaction_count", 0) or 0)
    interest = int(float(state.get("interest", 0.0) or 0.0) * 100)
    attraction = int(float(state.get("attraction", 0.0) or 0.0) * 100)
    control = int(float(state.get("control", 0.0) or 0.0) * 100)
    return interaction_count + interest + attraction + control + len(strategy)


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _trim_sentences(text: str, *, max_sentences: int) -> str:
    if not text:
        return text
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if len(parts) <= max_sentences:
        return text
    return " ".join(parts[:max_sentences]).strip()


def _ensure_terminal_punctuation(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _merge_hook(text: str, hook: str) -> str:
    trailing = text[-1] if text[-1] in ".!?" else ""
    body = text[:-1].rstrip() if trailing else text
    if not body:
        return text

    connector = " " if body.endswith(("—", "-", ":", ";", ",")) else ", "
    return f"{body}{connector}{hook}{trailing or '.'}"
