import re
from datetime import datetime, timezone
from typing import Any


class KeywordMemoryService:
    MAX_ITEMS_PER_CATEGORY = 5

    def apply(self, state: dict[str, Any], message_text: str) -> dict[str, Any]:
        updated_state = state.copy()
        memory_flags = dict(updated_state.get("memory_flags") or {})
        support_profile = dict(memory_flags.get("support_profile") or {})
        support_stats = dict(memory_flags.get("support_stats") or {})

        extracted = self._extract(message_text)
        grounding_kind = self.detect_grounding_need(message_text)

        if not extracted and grounding_kind is None:
            updated_state["memory_flags"] = memory_flags
            return updated_state

        for category, values in extracted.items():
            existing = list(support_profile.get(category) or [])
            for value in values:
                existing = self._upsert(existing, value)
            support_profile[category] = existing[: self.MAX_ITEMS_PER_CATEGORY]

        if grounding_kind is not None:
            support_stats = self._increment_stat(support_stats, grounding_kind)

        memory_flags["support_profile"] = support_profile
        memory_flags["support_stats"] = support_stats
        updated_state["memory_flags"] = memory_flags
        return updated_state

    def build_prompt_context(self, state: dict[str, Any]) -> str:
        support_profile = (
            state.get("memory_flags", {}).get("support_profile", {})
            if isinstance(state.get("memory_flags"), dict)
            else {}
        )
        if not support_profile:
            return ""

        labels = {
            "triggers": "Известные триггеры",
            "symptoms": "Повторяющиеся симптомы",
            "coping_tools": "Что помогает пользователю",
            "support_preferences": "Как лучше поддерживать",
            "important_context": "Важный контекст",
        }

        lines: list[str] = []
        for key in [
            "triggers",
            "symptoms",
            "coping_tools",
            "support_preferences",
            "important_context",
        ]:
            items = support_profile.get(key) or []
            if not items:
                continue

            values = [item["value"] for item in items if item.get("value")]
            if values:
                lines.append(f"- {labels[key]}: " + "; ".join(values))

        return "\n".join(lines)

    def detect_grounding_need(self, text: str) -> str | None:
        lowered = " ".join(text.lower().split())

        if any(phrase in lowered for phrase in [
            "паника",
            "паническая атака",
            "меня трясет",
            "не могу успокоиться",
            "накрывает тревога",
        ]):
            return "panic"

        if any(phrase in lowered for phrase in [
            "флэшбек",
            "флешбек",
            "снова как тогда",
            "накрыло воспоминаниями",
            "будто это происходит снова",
        ]):
            return "flashback"

        if any(phrase in lowered for phrase in [
            "не могу уснуть",
            "бессонница",
            "не сплю",
            "снова не спится",
            "боюсь засыпать",
        ]):
            return "insomnia"

        return None

    def build_grounding_response(self, kind: str) -> str:
        responses = {
            "panic": (
                "Я рядом.\n\n"
                "Сейчас не нужно решать все сразу.\n"
                "Посмотри вокруг и назови про себя 3 предмета, которые видишь.\n"
                "Сделай один медленный выдох длиннее вдоха.\n"
                "Если можешь, упрись стопами в пол и почувствуй опору."
            ),
            "flashback": (
                "Похоже, тебя сильно накрывает воспоминанием.\n\n"
                "Попробуй мягко напомнить себе: это сейчас не происходит, ты в текущем моменте.\n"
                "Осмотрись вокруг и назови дату, место и 3 реальных предмета рядом.\n"
                "Если помогает, коснись чего-то холодного или плотного, чтобы вернуть ощущение настоящего."
            ),
            "insomnia": (
                "Ночь может усиливать напряжение.\n\n"
                "Не заставляй себя уснуть любой ценой.\n"
                "Попробуй убрать яркий свет, сделать несколько медленных выдохов и сосредоточиться на одной спокойной детали вокруг.\n"
                "Если хочешь, я побуду с тобой коротко и спокойно."
            ),
        }
        return responses.get(kind, "")

    def _extract(self, text: str) -> dict[str, list[str]]:
        lowered = " ".join(text.lower().split())
        result: dict[str, list[str]] = {}

        for category, value in [
            ("coping_tools", self._extract_phrase(lowered, r"(?:мне помогает|меня успокаивает|мне легче, когда)\s+([^.!?]+)")),
            ("support_preferences", self._extract_phrase(lowered, r"(?:мне важно, чтобы|лучше со мной|со мной лучше)\s+([^.!?]+)")),
            ("triggers", self._extract_phrase(lowered, r"(?:меня триггерит|мой триггер|меня пугает|меня накрывает от)\s+([^.!?]+)")),
            ("important_context", self._extract_phrase(lowered, r"(?:у меня птср|у меня травма|после войны|после службы|после того случая)\s*([^.!?]*)")),
        ]:
            if value:
                result.setdefault(category, []).append(value)

        symptom_keywords = {
            "flashbacks": "флэшбеки или навязчивые воспоминания",
            "nightmares": "кошмары",
            "panic": "панические реакции",
            "dissociation": "диссоциация или ощущение нереальности",
            "hypervigilance": "гипербдительность",
            "avoidance": "избегание триггеров",
            "insomnia": "проблемы со сном",
        }

        keyword_map = {
            "flashbacks": ["флэшбек", "флешбек", "навязчивые воспоминания"],
            "nightmares": ["кошмар", "снятся кошмары", "плохие сны"],
            "panic": ["паника", "паническая атака", "накрывает тревога"],
            "dissociation": ["диссоциация", "нереально", "будто не здесь"],
            "hypervigilance": ["напрягаюсь от звуков", "вздрагиваю", "гипербдительность"],
            "avoidance": ["избегаю", "стараюсь не вспоминать", "не могу касаться этой темы"],
            "insomnia": ["не могу уснуть", "плохо сплю", "бессонница"],
        }

        matched_symptoms = [
            symptom_keywords[key]
            for key, patterns in keyword_map.items()
            if any(pattern in lowered for pattern in patterns)
        ]
        if matched_symptoms:
            result["symptoms"] = matched_symptoms

        if any(phrase in lowered for phrase in ["без советов", "не давай советов", "просто побудь рядом"]):
            result.setdefault("support_preferences", []).append("лучше меньше советов и больше спокойного присутствия")

        if any(phrase in lowered for phrase in ["коротко", "без длинных ответов", "не пиши много"]):
            result.setdefault("support_preferences", []).append("лучше отвечать короче и спокойнее")

        if any(phrase in lowered for phrase in ["дыхание помогает", "дышать помогает", "заземление помогает", "вода помогает", "музыка помогает"]):
            result.setdefault("coping_tools", []).append("помогают простые техники саморегуляции")

        return result

    def _extract_phrase(self, text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None

        value = match.group(1).strip(" ,.;:!-")
        if not value:
            return None
        return value[:160]

    def _upsert(self, items: list[dict[str, str]], value: str) -> list[dict[str, str]]:
        normalized_value = value.strip()
        now = datetime.now(timezone.utc).isoformat()

        filtered = [item for item in items if item.get("value") != normalized_value]
        filtered.insert(
            0,
            {
                "value": normalized_value,
                "updated_at": now,
            },
        )
        return filtered

    def _increment_stat(self, stats: dict[str, Any], kind: str) -> dict[str, Any]:
        counters = dict(stats.get("episode_counts") or {})
        entry = {
            "count": int(counters.get(kind, {}).get("count", 0)) + 1,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        counters[kind] = entry
        stats["episode_counts"] = counters
        return stats
