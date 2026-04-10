import re
from typing import Any


class IntentRouter:
    DIRECT_QUESTION_STARTS = (
        "почему",
        "как ",
        "что ",
        "зачем",
        "когда",
        "где",
        "кто",
        "можешь",
        "подскажи",
        "стоит ли",
        "can you ",
        "could you ",
        "how ",
        "what ",
        "why ",
        "when ",
        "where ",
        "who ",
    )
    SUPPORT_MARKERS = (
        "мне тяжело",
        "я устал",
        "я боюсь",
        "я переживаю",
        "тревог",
        "нет сил",
        "накрыло",
        "мне плохо",
        "тяжело",
        "страшно",
        "одиноко",
    )
    FLIRT_MARKERS = (
        "скучаю",
        "хочу тебя",
        "поцел",
        "обними",
        "обнять",
        "флирт",
        "сексу",
        "эрот",
    )
    SMALLTALK_MARKERS = (
        "привет",
        "доброе утро",
        "доброй ночи",
        "как дела",
        "ты тут",
        "ахаха",
        "лол",
        "хех",
    )

    def classify(
        self,
        *,
        user_message: str,
        state: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
        active_mode: str = "base",
    ) -> dict[str, Any]:
        text = " ".join((user_message or "").strip().split())
        lowered = text.lower()
        emotional_tone = str((state or {}).get("emotional_tone") or "neutral")
        message_length = len(text)

        intent = "discussion"
        if "?" in text or lowered.startswith(self.DIRECT_QUESTION_STARTS):
            intent = "direct_answer"
        elif self._contains_any(lowered, self.SUPPORT_MARKERS) or emotional_tone in {
            "overwhelmed",
            "anxious",
            "guarded",
        }:
            intent = "support"
        elif active_mode in {"passion", "night", "dominant"} or self._contains_any(lowered, self.FLIRT_MARKERS):
            intent = "flirty"
        elif self._contains_any(lowered, self.SMALLTALK_MARKERS):
            intent = "smalltalk"

        desired_length = "medium"
        if message_length <= 30 and "?" not in text:
            desired_length = "brief"
        elif message_length >= 280:
            desired_length = "detailed"
        elif intent in {"smalltalk", "flirty"} and message_length <= 80:
            desired_length = "brief"
        elif intent == "support" and message_length >= 160:
            desired_length = "medium"

        needs_clarification = False
        if intent == "direct_answer":
            token_count = len(re.findall(r"\w+", lowered))
            broad_request = token_count <= 3 and "?" not in text
            needs_clarification = broad_request

        should_end_with_question = intent in {"support", "smalltalk", "flirty"}
        if desired_length == "brief" and intent == "direct_answer":
            should_end_with_question = False

        use_memory = intent in {"support", "flirty", "discussion"} or active_mode in {"comfort", "ptsd", "free_talk"}

        return {
            "intent": intent,
            "desired_length": desired_length,
            "needs_clarification": needs_clarification,
            "should_end_with_question": should_end_with_question,
            "use_memory": use_memory,
            "emotional_tone": emotional_tone,
            "message_length": message_length,
            "history_turns": len(history or []),
        }

    def _contains_any(self, text: str, markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)
