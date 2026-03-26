import re
from datetime import datetime, timezone
from typing import Any


class KeywordMemoryService:
    MAX_ITEMS_PER_CATEGORY = 5
    MAX_PROFILE_ITEMS = 6

    def apply(self, state: dict[str, Any], message_text: str) -> dict[str, Any]:
        updated_state = state.copy()
        memory_flags = dict(updated_state.get("memory_flags") or {})
        support_profile = dict(memory_flags.get("support_profile") or {})
        support_stats = dict(memory_flags.get("support_stats") or {})
        user_profile = self._normalize_user_profile(updated_state.get("user_profile"))

        extracted = self._extract(message_text)
        profile_updates = self._extract_user_profile(message_text)
        episodic_updates = self._extract_episodic_memory(message_text)
        grounding_kind = self.detect_grounding_need(message_text)

        if not extracted and grounding_kind is None and not profile_updates and not episodic_updates:
            updated_state["user_profile"] = user_profile
            updated_state["memory_flags"] = memory_flags
            return updated_state

        for category, values in profile_updates.items():
            existing = list(user_profile.get(category) or [])
            for value in values:
                existing = self._upsert_text(existing, value)
            user_profile[category] = existing[: self.MAX_PROFILE_ITEMS]

        for category, values in extracted.items():
            existing = list(support_profile.get(category) or [])
            for value in values:
                existing = self._upsert(existing, value)
            support_profile[category] = existing[: self.MAX_ITEMS_PER_CATEGORY]

        for category, values in episodic_updates.items():
            existing = list(memory_flags.get(category) or [])
            for value in values:
                existing = self._upsert(existing, value)
            memory_flags[category] = existing[: self.MAX_ITEMS_PER_CATEGORY]

        if grounding_kind is not None:
            support_stats = self._increment_stat(support_stats, grounding_kind)

        updated_state["user_profile"] = user_profile
        memory_flags["support_profile"] = support_profile
        memory_flags["support_stats"] = support_stats
        updated_state["memory_flags"] = memory_flags
        return updated_state

    def build_prompt_context(
        self,
        state: dict[str, Any],
        history: list[Any] | None = None,
    ) -> str:
        user_profile = (
            state.get("user_profile", {})
            if isinstance(state.get("user_profile"), dict)
            else {}
        )
        memory_flags = (
            state.get("memory_flags", {})
            if isinstance(state.get("memory_flags"), dict)
            else {}
        )
        support_profile = (
            memory_flags.get("support_profile", {})
            if isinstance(memory_flags.get("support_profile"), dict)
            else {}
        )

        lines: list[str] = []

        traits = self._collect_profile_values(user_profile, "personality_traits")
        goals = self._collect_profile_values(user_profile, "goals")
        interests = self._collect_profile_values(user_profile, "interests")
        current_focus = self._collect_memory_values(memory_flags, "current_focus")
        open_loops = self._collect_memory_values(memory_flags, "open_loops")
        recent_topics = [
            value
            for value in self._collect_memory_values(memory_flags, "recent_topics")
            if value not in current_focus
        ]
        episodic_summary = memory_flags.get("episodic_summary") or {}

        if isinstance(episodic_summary, dict):
            recent_arc = self._clean_summary_value(episodic_summary.get("recent_arc"))
            emotional_direction = self._clean_summary_value(episodic_summary.get("emotional_direction"))
            open_loop_summary = self._clean_summary_value(episodic_summary.get("open_loops"))
            response_hint = self._clean_summary_value(episodic_summary.get("response_hint"))
            if recent_arc:
                lines.append("- Recent arc between user and Lira: " + recent_arc)
            if emotional_direction:
                lines.append("- Emotional direction lately: " + emotional_direction)
            if open_loop_summary:
                lines.append("- Unresolved thread from the dialogue: " + open_loop_summary)
            if response_hint:
                lines.append("- What kind of reply may fit next: " + response_hint)

        if traits:
            lines.append("- Stable traits or patterns: " + "; ".join(traits))
        if goals:
            lines.append("- Ongoing wishes or goals: " + "; ".join(goals))
        if interests:
            lines.append("- Interests and energizing topics: " + "; ".join(interests))
        if current_focus:
            lines.append("- What feels alive lately: " + "; ".join(current_focus))
        if open_loops:
            lines.append("- Open loops worth remembering: " + "; ".join(open_loops))
        if recent_topics:
            lines.append("- Recent recurring topics: " + "; ".join(recent_topics))

        support_labels = {
            "support_preferences": "How they prefer to be responded to",
            "coping_tools": "What tends to help",
            "triggers": "Known triggers",
            "symptoms": "Recurring symptoms or strain patterns",
            "important_context": "Important background context",
        }
        for key in (
            "support_preferences",
            "coping_tools",
            "triggers",
            "symptoms",
            "important_context",
        ):
            items = support_profile.get(key) or []
            values = [item["value"] for item in items if isinstance(item, dict) and item.get("value")]
            if values:
                lines.append(f"- {support_labels[key]}: " + "; ".join(values))

        recent_thread = self._build_recent_thread(history or [])
        if recent_thread:
            lines.append("- Recent thread still in the air: " + recent_thread)

        return "\n".join(lines)

    def detect_grounding_need(self, text: str) -> str | None:
        lowered = " ".join(text.lower().split())

        if any(
            phrase in lowered
            for phrase in [
                "паника",
                "паническая атака",
                "меня трясет",
                "не могу успокоиться",
                "накрывает тревога",
            ]
        ):
            return "panic"

        if any(
            phrase in lowered
            for phrase in [
                "флэшбек",
                "флешбек",
                "снова как тогда",
                "накрыло воспоминаниями",
                "будто это происходит снова",
            ]
        ):
            return "flashback"

        if any(
            phrase in lowered
            for phrase in [
                "не могу уснуть",
                "бессонница",
                "не сплю",
                "снова не спится",
                "боюсь засыпать",
            ]
        ):
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
                "Попробуй убрать яркий свет, сделать несколько медленных выдохов "
                "и сосредоточиться на одной спокойной детали вокруг.\n"
                "Если хочешь, я побуду с тобой коротко и спокойно."
            ),
        }
        return responses.get(kind, "")

    def _extract(self, text: str) -> dict[str, list[str]]:
        lowered = " ".join(text.lower().split())
        result: dict[str, list[str]] = {}

        for category, value in [
            (
                "coping_tools",
                self._extract_phrase(
                    lowered,
                    r"(?:мне помогает|меня успокаивает|мне легче, когда)\s+([^.!?]+?)(?:\s+и\s+лучше\b|$)",
                ),
            ),
            (
                "support_preferences",
                self._extract_phrase(
                    lowered,
                    r"(?:мне важно, чтобы|лучше со мной|со мной лучше)\s+([^.!?]+)",
                ),
            ),
            (
                "triggers",
                self._extract_phrase(
                    lowered,
                    r"(?:меня триггерит|мой триггер|меня пугает|меня накрывает от)\s+([^.!?]+)",
                ),
            ),
            (
                "important_context",
                self._extract_phrase(
                    lowered,
                    r"(?:у меня птср|у меня травма|после войны|после службы|после того случая)\s*([^.!?]*)",
                ),
            ),
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

        if any(
            phrase in lowered
            for phrase in ["без советов", "не давай советов", "просто побудь рядом", "без длинных советов"]
        ):
            result.setdefault("support_preferences", []).append(
                "лучше меньше советов и больше спокойного присутствия"
            )

        if any(
            phrase in lowered
            for phrase in ["коротко", "без длинных ответов", "не пиши много"]
        ):
            result.setdefault("support_preferences", []).append(
                "лучше отвечать короче и спокойнее"
            )

        if any(
            phrase in lowered
            for phrase in [
                "дыхание помогает",
                "дышать помогает",
                "заземление помогает",
                "вода помогает",
                "музыка помогает",
            ]
        ):
            result.setdefault("coping_tools", []).append(
                "помогают простые техники саморегуляции"
            )

        return result

    def _extract_user_profile(self, text: str) -> dict[str, list[str]]:
        lowered = " ".join(text.lower().split())
        result: dict[str, list[str]] = {}

        for category, value in [
            (
                "goals",
                self._extract_phrase(
                    lowered,
                    r"(?:я хочу|мне хочется|мне нужно|я пытаюсь|я стараюсь|моя цель)\s+([^,.!?]+)",
                ),
            ),
            (
                "interests",
                self._extract_phrase(
                    lowered,
                    r"(?:я люблю|мне нравится|я увлекаюсь|интересуюсь|мне интересны)\s+([^,.!?]+)",
                ),
            ),
            (
                "personality_traits",
                self._extract_phrase(
                    lowered,
                    r"(?:я обычно|я по жизни|я человек, который|мне сложно|мне легко|я довольно)\s+([^,.!?]+)",
                ),
            ),
        ]:
            if value:
                result.setdefault(category, []).append(value)

        return result

    def _extract_episodic_memory(self, text: str) -> dict[str, list[str]]:
        lowered = " ".join(text.lower().split())
        result: dict[str, list[str]] = {}

        focus_patterns = [
            r"(?:сейчас|в последнее время|сегодня|на этой неделе)\s+([^.!?]+)",
            r"(?:я сейчас|я в последнее время|я сегодня)\s+([^.!?]+)",
        ]
        loop_patterns = [
            r"(?:мне нужно|надо|я пытаюсь|я стараюсь|хочу разобраться|не могу отпустить|не знаю как)\s+([^.!?]+)",
            r"(?:завтра|сегодня вечером|на днях)\s+([^.!?]+)",
        ]

        for pattern in focus_patterns:
            value = self._extract_phrase(lowered, pattern)
            if value:
                result.setdefault("current_focus", []).append(value)

        for pattern in loop_patterns:
            value = self._extract_phrase(lowered, pattern)
            if value:
                result.setdefault("open_loops", []).append(value)

        topic = self._extract_recent_topic(lowered)
        if topic:
            result.setdefault("recent_topics", []).append(topic)

        return result

    def _extract_recent_topic(self, text: str) -> str | None:
        for marker in (
            "работ",
            "отношени",
            "семь",
            "тревог",
            "сон",
            "устал",
            "учеб",
            "деньг",
            "будущ",
            "ссор",
        ):
            if marker in text:
                return self._clip_phrase(text)
        return None

    def _extract_phrase(self, text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None

        value = match.group(1).strip(" ,.;:!-")
        if not value:
            return None
        return value[:160]

    def _clip_phrase(self, text: str) -> str | None:
        cleaned = text.strip(" ,.;:!-")
        if not cleaned:
            return None
        return cleaned[:160]

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

    def _upsert_text(self, items: list[str], value: str) -> list[str]:
        normalized_value = value.strip()
        if not normalized_value:
            return items
        filtered = [item for item in items if item != normalized_value]
        filtered.insert(0, normalized_value)
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

    def _normalize_user_profile(self, payload: Any) -> dict[str, list[str]]:
        profile = payload if isinstance(payload, dict) else {}
        return {
            "goals": list(profile.get("goals") or []),
            "interests": list(profile.get("interests") or []),
            "personality_traits": list(profile.get("personality_traits") or []),
        }

    def _collect_profile_values(self, profile: dict[str, Any], key: str) -> list[str]:
        return [value for value in list(profile.get(key) or []) if value][: self.MAX_PROFILE_ITEMS]

    def _collect_memory_values(self, memory_flags: dict[str, Any], key: str) -> list[str]:
        items = list(memory_flags.get(key) or [])
        return [item["value"] for item in items if isinstance(item, dict) and item.get("value")]

    def _build_recent_thread(self, history: list[Any]) -> str:
        snippets: list[str] = []
        for message in reversed(history):
            if getattr(message, "role", None) != "user":
                continue

            content = " ".join(str(getattr(message, "content", "")).split()).strip()
            if len(content) < 20:
                continue

            snippet = content[:120]
            if snippet not in snippets:
                snippets.append(snippet)

            if len(snippets) >= 2:
                break

        snippets.reverse()
        return " | ".join(snippets)

    def _clean_summary_value(self, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()[:180]
