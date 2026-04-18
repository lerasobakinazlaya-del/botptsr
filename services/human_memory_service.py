import re
from datetime import datetime, timezone
from typing import Any

from services.prompt_safety import sanitize_memory_value


class HumanMemoryService:
    MAX_ITEMS_PER_LIST = 6
    MAX_CALLBACK_CANDIDATES = 3
    MAX_PROMPT_CALLBACK_CANDIDATES = 2
    INACTIVITY_DECAY_GRACE_HOURS = 72
    REENGAGEMENT_STARTER_FAMILIES = (
        "soft_presence",
        "callback_thread",
        "mood_ping",
        "playful_hook",
    )

    INTEREST_PATTERNS = [
        r"(?:я люблю|мне нравится|обожаю|увлекаюсь|интересуюсь)\s+([^.!?\n]+)",
    ]
    GOAL_PATTERNS = [
        r"(?:я хочу|мне нужно|моя цель|хочу научиться|хочу понять)\s+([^.!?\n]+)",
    ]
    TRAIT_PATTERNS = [
        r"(?:я человек|я обычно|по характеру я)\s+([^.!?\n]+)",
    ]
    NAME_PATTERNS = [
        r"(?:меня зовут|моё имя|мое имя)\s+([а-яa-zё-]{2,40})",
    ]
    IMPORTANT_PERSON_PATTERNS = {
        "жену пользователя зовут": r"(?:мою жену зовут)\s+([а-яa-zё-]{2,40})",
        "девушку пользователя зовут": r"(?:мою девушку зовут)\s+([а-яa-zё-]{2,40})",
        "парня пользователя зовут": r"(?:моего парня зовут)\s+([а-яa-zё-]{2,40})",
        "мужа пользователя зовут": r"(?:моего мужа зовут)\s+([а-яa-zё-]{2,40})",
        "подругу пользователя зовут": r"(?:мою подругу зовут)\s+([а-яa-zё-]{2,40})",
        "друга пользователя зовут": r"(?:моего друга зовут)\s+([а-яa-zё-]{2,40})",
    }

    TOPIC_KEYWORDS = {
        "работа и дела": ["работа", "проект", "задача", "клиент", "дедлайн", "учеб", "экзамен"],
        "отношения": ["отношения", "девушка", "парень", "любовь", "семья", "общение", "ссора"],
        "саморазвитие": ["привыч", "рост", "развив", "цель", "мотивац", "дисциплин"],
        "творчество": ["музык", "рисую", "пишу", "творч", "дизайн", "фото"],
        "техника": ["код", "бот", "программ", "ai", "ии", "нейросет", "ноутбук"],
        "отдых": ["кино", "сериал", "игра", "отдых", "прогул", "путешеств"],
    }

    POSITIVE_MARKERS = ["спасибо", "нравится", "приятно", "люблю", "класс", "здорово", "хорошо"]
    OPENNESS_MARKERS = ["чувствую", "боюсь", "переживаю", "для меня важно", "мне сложно", "я устал", "я хочу"]
    PLAYFUL_MARKERS = [")", "ахаха", "шучу", "смешно", "лол", "хех"]
    BRIEF_PREFERENCE_MARKERS = ["короче", "кратко", "без длинных ответов", "не пиши много"]
    DETAILED_PREFERENCE_MARKERS = ["подробно", "развернуто", "объясни глубже", "можно подробнее"]
    INITIATIVE_PREFERENCE_MARKERS = ["пиши первым", "сама пиши", "напоминай", "проявляй инициативу"]
    QUESTION_PREFERENCE_MARKERS = ["задавай вопросы", "спрашивай меня", "хочу диалог"]

    def apply_user_message(self, state: dict[str, Any], message_text: str) -> dict[str, Any]:
        current_state = (state or {}).copy()
        normalized_text = " ".join((message_text or "").strip().split())
        if not normalized_text:
            return current_state

        profile = self._normalize_profile(current_state.get("user_profile"))
        relationship = self._apply_inactivity_decay(
            self._normalize_relationship(current_state.get("relationship_state"))
        )
        lowered = normalized_text.lower()

        for value in self._extract_patterns(lowered, self.INTEREST_PATTERNS):
            profile["interests"] = self._remember(profile["interests"], value)
            relationship["callback_candidates"] = self._remember_callback(
                relationship["callback_candidates"],
                value,
            )

        for value in self._extract_patterns(lowered, self.GOAL_PATTERNS):
            profile["goals"] = self._remember(profile["goals"], value)
            relationship["callback_candidates"] = self._remember_callback(
                relationship["callback_candidates"],
                value,
            )

        for value in self._extract_patterns(lowered, self.TRAIT_PATTERNS):
            profile["personality_traits"] = self._remember(profile["personality_traits"], value)

        for value in self._extract_name_facts(lowered):
            profile["identity_facts"] = self._remember(profile["identity_facts"], value)

        detected_topics = self._detect_topics(lowered)
        for topic in detected_topics:
            profile["recurring_topics"] = self._remember(profile["recurring_topics"], topic)
            relationship["shared_threads"] = self._remember(relationship["shared_threads"], topic)

        relationship["communication_style"] = self._update_style(
            relationship.get("communication_style"),
            normalized_text,
        )
        relationship["response_preferences"] = self._update_preferences(
            relationship.get("response_preferences"),
            lowered,
        )
        relationship["last_user_mood"] = self._detect_mood(lowered)
        relationship["last_user_topic"] = detected_topics[0] if detected_topics else relationship.get("last_user_topic")
        relationship["trust"] = self._shift_metric(
            relationship["trust"],
            0.03 if self._contains_any(lowered, self.OPENNESS_MARKERS) else 0.01,
        )
        relationship["familiarity"] = self._shift_metric(
            relationship["familiarity"],
            0.02 if len(normalized_text) > 80 else 0.01,
        )
        if self._contains_any(lowered, self.PLAYFUL_MARKERS):
            relationship["playfulness"] = self._shift_metric(relationship["playfulness"], 0.04)
        if self._contains_any(lowered, self.POSITIVE_MARKERS):
            relationship["warmth"] = self._shift_metric(relationship["warmth"], 0.03)

        relationship["last_user_message_at"] = self._now_iso()
        relationship["last_interaction_at"] = relationship["last_user_message_at"]

        current_state["user_profile"] = profile
        current_state["relationship_state"] = relationship
        current_state.setdefault("reengagement", {})
        return current_state

    def apply_assistant_message(
        self,
        state: dict[str, Any],
        assistant_text: str,
        *,
        source: str = "reply",
    ) -> dict[str, Any]:
        current_state = (state or {}).copy()
        relationship = self._apply_inactivity_decay(
            self._normalize_relationship(current_state.get("relationship_state"))
        )
        relationship["last_assistant_message_at"] = self._now_iso()
        relationship["last_interaction_at"] = relationship["last_assistant_message_at"]

        if source == "reengagement":
            reengagement = dict(current_state.get("reengagement") or {})
            reengagement["last_sent_at"] = relationship["last_assistant_message_at"]
            reengagement["last_triggered_from_user_at"] = relationship.get("last_user_message_at")
            reengagement["sent_count"] = self._coerce_int(reengagement.get("sent_count"), 0) + 1
            current_state["reengagement"] = reengagement

        current_state["relationship_state"] = relationship
        return current_state

    def build_prompt_context(self, state: dict[str, Any]) -> str:
        profile = self._normalize_profile((state or {}).get("user_profile"))
        relationship = self._normalize_relationship((state or {}).get("relationship_state"))

        lines: list[str] = []
        if profile["interests"]:
            lines.append("- Интересы пользователя: " + "; ".join(profile["interests"]))
        if profile["goals"]:
            lines.append("- Цели и желания: " + "; ".join(profile["goals"]))
        if profile["personality_traits"]:
            lines.append("- Черты пользователя: " + "; ".join(profile["personality_traits"]))
        if profile["recurring_topics"]:
            lines.append("- Повторяющиеся темы: " + "; ".join(profile["recurring_topics"]))
        if profile["identity_facts"]:
            lines.append("- Важные имена и связи: " + "; ".join(profile["identity_facts"]))
        if relationship["shared_threads"]:
            lines.append("- Нити прошлых разговоров: " + "; ".join(relationship["shared_threads"]))
        if relationship["callback_candidates"]:
            lines.append(
                "- Что можно мягко вспомнить позже: "
                + "; ".join(relationship["callback_candidates"][: self.MAX_PROMPT_CALLBACK_CANDIDATES])
            )
        if relationship.get("last_user_mood"):
            lines.append(f"- Последний заметный эмоциональный фон: {relationship['last_user_mood']}")

        style_line = self._build_style_line(relationship)
        if style_line:
            lines.append(style_line)

        chemistry_line = self._build_chemistry_line(relationship)
        if chemistry_line:
            lines.append(chemistry_line)

        return "\n".join(lines)

    def suggest_mode(self, state: dict[str, Any], current_mode: str) -> str:
        if current_mode not in {"base", "comfort"}:
            return current_mode

        if current_mode == "comfort":
            return "comfort"

        relationship = self._normalize_relationship((state or {}).get("relationship_state"))
        mood = str(relationship.get("last_user_mood") or "")
        topic = str(relationship.get("last_user_topic") or "")

        if mood in {"тревога или внутреннее напряжение", "усталость или перегруз", "нужда в контакте или тепле"}:
            return "comfort"

        if topic in {"работа и дела", "саморазвитие"} and relationship.get("trust", 0.0) > 0.32:
            return "comfort"

        return "base"

    def build_reengagement_prompt(
        self,
        state: dict[str, Any],
        *,
        hours_silent: int,
        active_mode: str,
        style_settings: dict[str, Any] | None = None,
    ) -> str:
        context = self.get_reengagement_context(state)
        topic = context["topic"]
        callback_hint = context["callback_hint"]
        relationship = self._normalize_relationship((state or {}).get("relationship_state"))
        reengagement = dict((state or {}).get("reengagement") or {})
        profile = self._normalize_profile((state or {}).get("user_profile"))
        sent_count = self._coerce_int(reengagement.get("sent_count"), 0)
        preference = self._render_preferences(relationship.get("response_preferences", {}))
        style = style_settings or {}
        stage = self._resolve_reengagement_stage(hours_silent)
        name_hint = self._extract_name_hint(profile.get("identity_facts") or [])
        last_mood = str(relationship.get("last_user_mood") or "").strip()
        starter_family = self._select_reengagement_starter_family(
            sent_count=sent_count,
            callback_hint=callback_hint,
            topic=topic,
            relationship=relationship,
            allowed_families=style.get("enabled_families"),
            prefer_callback_thread=bool(style.get("prefer_callback_thread", True)),
        )

        parts = [
            "The user has been quiet for a while.",
            f"Silence is roughly {hours_silent} hours.",
            f"Active mode: {active_mode}.",
            "Write one short, alive first-message opener.",
            "It should feel natural, warm, human, and easy to answer.",
            "Do not mention rules, tokens, settings, access, or automation.",
            "If it fits, gently pick up a thread from the earlier conversation.",
            "Keep it to at most two short paragraphs and no lists.",
            f"Target length: up to {max(120, int(style.get('max_chars', 220) or 220))} characters if possible.",
            "Do not reuse the same opener shape every time.",
            f"Retention stage: {stage}.",
            self._build_reengagement_stage_guidance(stage),
            f"For this message, prefer the opener family: {starter_family}.",
            self._build_reengagement_starter_guidance(starter_family, active_mode=active_mode),
        ]
        if bool(style.get("allow_question", True)):
            parts.append("One light, easy-to-answer question is allowed near the end.")
        else:
            parts.append("Do not end with a question. Let the opener stand on its own.")
        if topic:
            parts.append(f"Last important user topic: {topic}.")
        if callback_hint:
            parts.append(f"You may lean on this as a soft callback: {callback_hint}.")
        if preference:
            parts.append(f"User style preference: {preference}.")
        if name_hint:
            parts.append(f"If it feels natural, you may softly use the user's name: {name_hint}.")
        if last_mood:
            parts.append(f"Last notable mood: {last_mood}. Avoid escalating it; meet it gently.")

        return "\n".join(parts)

    def get_reengagement_context(self, state: dict[str, Any]) -> dict[str, str]:
        relationship = self._normalize_relationship((state or {}).get("relationship_state"))
        profile = self._normalize_profile((state or {}).get("user_profile"))
        topic = relationship.get("last_user_topic") or (
            profile["recurring_topics"][0] if profile["recurring_topics"] else ""
        )
        callback_hint = relationship["callback_candidates"][0] if relationship["callback_candidates"] else ""
        return {
            "topic": str(topic or "").strip(),
            "callback_hint": str(callback_hint or "").strip(),
            "name_hint": self._extract_name_hint(profile["identity_facts"]),
            "last_mood": str(relationship.get("last_user_mood") or "").strip(),
        }

    def get_reengagement_metadata(self, state: dict[str, Any]) -> dict[str, Any]:
        return dict((state or {}).get("reengagement") or {})

    def can_send_reengagement(
        self,
        state: dict[str, Any],
        *,
        min_hours_between: int,
        last_user_message_at: str | None,
        callback_topic: str | None = None,
    ) -> bool:
        meta = self.get_reengagement_metadata(state)
        last_sent_at = meta.get("last_sent_at")
        if last_sent_at and self._hours_since(last_sent_at) < max(1, min_hours_between):
            return False

        if not last_user_message_at:
            return False

        last_triggered_from_user_at = meta.get("last_triggered_from_user_at")
        if last_triggered_from_user_at and last_triggered_from_user_at == last_user_message_at:
            return False

        normalized_callback_topic = str(callback_topic or "").strip().lower()
        if normalized_callback_topic:
            last_callback_topic = str(meta.get("last_callback_topic") or "").strip().lower()
            if last_callback_topic == normalized_callback_topic:
                return False

        return True

    def mark_reengagement_callback(self, state: dict[str, Any], callback_topic: str | None) -> dict[str, Any]:
        normalized_topic = str(callback_topic or "").strip()
        if not normalized_topic:
            return dict(state or {})

        updated = dict(state or {})
        reengagement = dict(updated.get("reengagement") or {})
        reengagement["last_callback_topic"] = normalized_topic
        updated["reengagement"] = reengagement
        return updated

    def hours_since_iso(self, value: str | None, fallback: int = 24) -> int:
        parsed = self._parse_iso(value)
        if parsed is None:
            return fallback
        return max(1, int((datetime.now(timezone.utc) - parsed).total_seconds() // 3600))

    def _normalize_profile(self, raw: Any) -> dict[str, list[str]]:
        profile = raw if isinstance(raw, dict) else {}
        return {
            "goals": list(profile.get("goals") or []),
            "interests": list(profile.get("interests") or []),
            "personality_traits": list(profile.get("personality_traits") or []),
            "recurring_topics": list(profile.get("recurring_topics") or []),
            "identity_facts": list(profile.get("identity_facts") or []),
        }

    def _normalize_relationship(self, raw: Any) -> dict[str, Any]:
        relationship = raw if isinstance(raw, dict) else {}
        return {
            "trust": self._coerce_float(relationship.get("trust"), 0.18),
            "familiarity": self._coerce_float(relationship.get("familiarity"), 0.12),
            "warmth": self._coerce_float(relationship.get("warmth"), 0.18),
            "playfulness": self._coerce_float(relationship.get("playfulness"), 0.08),
            "shared_threads": list(relationship.get("shared_threads") or []),
            "callback_candidates": list(relationship.get("callback_candidates") or [])[: self.MAX_CALLBACK_CANDIDATES],
            "communication_style": dict(relationship.get("communication_style") or {}),
            "response_preferences": dict(relationship.get("response_preferences") or {}),
            "last_user_message_at": relationship.get("last_user_message_at"),
            "last_assistant_message_at": relationship.get("last_assistant_message_at"),
            "last_interaction_at": relationship.get("last_interaction_at"),
            "last_user_topic": relationship.get("last_user_topic"),
            "last_user_mood": relationship.get("last_user_mood"),
        }

    def _update_style(self, raw: Any, text: str) -> dict[str, Any]:
        style = dict(raw or {})
        previous_avg = self._coerce_float(style.get("avg_user_length"), float(len(text) or 1))
        current_len = float(len(text) or 1)
        style["avg_user_length"] = round(previous_avg * 0.8 + current_len * 0.2, 2)
        style["question_ratio"] = round(
            self._coerce_float(style.get("question_ratio"), 0.0) * 0.8 + (0.2 if "?" in text else 0.0),
            3,
        )
        style["emoji_ratio"] = round(
            self._coerce_float(style.get("emoji_ratio"), 0.0) * 0.8 + (0.2 if re.search(r"[()🙂😉😊😂]", text) else 0.0),
            3,
        )
        return style

    def _update_preferences(self, raw: Any, lowered: str) -> dict[str, Any]:
        preferences = dict(raw or {})
        if self._contains_any(lowered, self.BRIEF_PREFERENCE_MARKERS):
            preferences["length"] = "brief"
        if self._contains_any(lowered, self.DETAILED_PREFERENCE_MARKERS):
            preferences["length"] = "detailed"
        if self._contains_any(lowered, self.INITIATIVE_PREFERENCE_MARKERS):
            preferences["initiative"] = "high"
        if self._contains_any(lowered, self.QUESTION_PREFERENCE_MARKERS):
            preferences["questions"] = "welcome"
        return preferences

    def _build_style_line(self, relationship: dict[str, Any]) -> str:
        preferences = relationship.get("response_preferences", {})
        fragments: list[str] = []
        if preferences.get("length") == "brief":
            fragments.append("предпочитает ответы короче")
        if preferences.get("length") == "detailed":
            fragments.append("любит более развернутые ответы")
        if preferences.get("initiative") == "high":
            fragments.append("нормально относится к инициативе первой")
        if preferences.get("questions") == "welcome":
            fragments.append("хорошо воспринимает уточняющие вопросы")

        style = relationship.get("communication_style", {})
        avg_length = self._coerce_float(style.get("avg_user_length"), 0.0)
        if avg_length > 220:
            fragments.append("сам пишет подробно")
        elif avg_length and avg_length < 70:
            fragments.append("часто пишет коротко")

        return "- Наблюдения по стилю общения: " + ", ".join(fragments) if fragments else ""

    def _build_chemistry_line(self, relationship: dict[str, Any]) -> str:
        trust = relationship.get("trust", 0.0)
        familiarity = relationship.get("familiarity", 0.0)
        warmth = relationship.get("warmth", 0.0)
        playfulness = relationship.get("playfulness", 0.0)

        return (
            "- Динамика контакта: "
            f"доверие {round(trust, 2)}, близость {round(familiarity, 2)}, "
            f"тепло {round(warmth, 2)}, игривость {round(playfulness, 2)}."
        )

    def _detect_topics(self, lowered: str) -> list[str]:
        topics = [
            topic
            for topic, keywords in self.TOPIC_KEYWORDS.items()
            if any(keyword in lowered for keyword in keywords)
        ]
        return topics[:3]

    def _detect_mood(self, lowered: str) -> str | None:
        if any(word in lowered for word in ["устал", "выгор", "нет сил", "тяжело"]):
            return "усталость или перегруз"
        if any(word in lowered for word in ["рад", "счаст", "класс", "хорошо"]):
            return "подъем или хорошее настроение"
        if any(word in lowered for word in ["тревог", "пережив", "боюсь", "не по себе"]):
            return "тревога или внутреннее напряжение"
        if any(word in lowered for word in ["скучаю", "не хватает", "одиноко"]):
            return "нужда в контакте или тепле"
        return None

    def _extract_patterns(self, text: str, patterns: list[str]) -> list[str]:
        found: list[str] = []
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            value = sanitize_memory_value(match.group(1), max_chars=160)
            if value:
                found.append(value)
        return found

    def _remember(self, items: list[str], value: str) -> list[str]:
        normalized = sanitize_memory_value(value, max_chars=160)
        if not normalized:
            return items
        updated = [item for item in items if item != normalized]
        updated.insert(0, normalized)
        return updated[: self.MAX_ITEMS_PER_LIST]

    def _remember_callback(self, items: list[str], value: str) -> list[str]:
        normalized = sanitize_memory_value(value, max_chars=160)
        if not normalized:
            return list(items or [])
        updated = [item for item in (items or []) if item != normalized]
        updated.insert(0, normalized)
        return updated[: self.MAX_CALLBACK_CANDIDATES]

    def _extract_name_facts(self, lowered: str) -> list[str]:
        facts: list[str] = []

        for value in self._extract_patterns(lowered, self.NAME_PATTERNS):
            cleaned = self._clean_name(value)
            if cleaned:
                facts.append(f"пользователя зовут {cleaned}")

        for relation, pattern in self.IMPORTANT_PERSON_PATTERNS.items():
            match = re.search(pattern, lowered, re.IGNORECASE)
            if not match:
                continue
            cleaned = self._clean_name(match.group(1))
            if not cleaned:
                continue
            facts.append(f"{relation} {cleaned}")

        deduped: list[str] = []
        for fact in facts:
            if fact not in deduped:
                deduped.append(fact)
        return deduped[:3]

    def _clean_name(self, value: str) -> str:
        cleaned = sanitize_memory_value(value, max_chars=40)
        if not cleaned:
            return ""
        cleaned = cleaned.strip(" ,.!?;:-")
        if not re.fullmatch(r"[а-яa-zё-]{2,40}", cleaned, re.IGNORECASE):
            return ""
        return cleaned.capitalize()

    def _contains_any(self, text: str, markers: list[str]) -> bool:
        return any(marker in text for marker in markers)

    def _shift_metric(self, value: float, delta: float) -> float:
        return max(0.0, min(1.0, round(value + delta, 4)))

    def _coerce_float(self, value: Any, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _coerce_int(self, value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _apply_inactivity_decay(self, relationship: dict[str, Any]) -> dict[str, Any]:
        current = dict(relationship or {})
        parsed = self._parse_iso(current.get("last_interaction_at"))
        if parsed is None:
            return current

        hours_since = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
        if hours_since <= self.INACTIVITY_DECAY_GRACE_HOURS:
            return current

        decay_days = min(5.0, (hours_since - self.INACTIVITY_DECAY_GRACE_HOURS) / 24.0)
        current["trust"] = self._shift_metric(current.get("trust", 0.0), -0.015 * decay_days)
        current["warmth"] = self._shift_metric(current.get("warmth", 0.0), -0.02 * decay_days)
        current["playfulness"] = self._shift_metric(current.get("playfulness", 0.0), -0.025 * decay_days)
        current["callback_candidates"] = list(current.get("callback_candidates") or [])[: self.MAX_CALLBACK_CANDIDATES]
        return current

    def _render_preferences(self, preferences: dict[str, Any]) -> str:
        fragments: list[str] = []
        if preferences.get("length") == "brief":
            fragments.append("лучше писать компактно")
        if preferences.get("length") == "detailed":
            fragments.append("можно писать чуть глубже")
        if preferences.get("initiative") == "high":
            fragments.append("инициатива от тебя уместна")
        if preferences.get("questions") == "welcome":
            fragments.append("бережный вопрос в конце допустим")
        return ", ".join(fragments)

    def _select_reengagement_starter_family(
        self,
        *,
        sent_count: int,
        callback_hint: str,
        topic: str,
        relationship: dict[str, Any],
        allowed_families: list[str] | None = None,
        prefer_callback_thread: bool = True,
    ) -> str:
        families = [
            family
            for family in (allowed_families or self.REENGAGEMENT_STARTER_FAMILIES)
            if family in self.REENGAGEMENT_STARTER_FAMILIES
        ] or list(self.REENGAGEMENT_STARTER_FAMILIES)

        if prefer_callback_thread and "callback_thread" in families and (callback_hint or topic):
            return "callback_thread"

        family = families[max(0, sent_count) % len(families)]

        if family == "callback_thread" and not (callback_hint or topic):
            family = "soft_presence"
        if family == "playful_hook" and relationship.get("playfulness", 0.0) < 0.18:
            family = "mood_ping" if relationship.get("warmth", 0.0) > 0.24 else "soft_presence"

        return family

    def _resolve_reengagement_stage(self, hours_silent: int) -> str:
        if hours_silent >= 24 * 14:
            return "day_14_reopen"
        if hours_silent >= 24 * 7:
            return "day_7_reset"
        if hours_silent >= 24 * 3:
            return "day_3_reengage"
        return "day_1_checkin"

    def _build_reengagement_stage_guidance(self, stage: str) -> str:
        guidance = {
            "day_1_checkin": (
                "Stage day_1_checkin: sound like a light daily check-in. "
                "Keep it easy, warm, and low-pressure."
            ),
            "day_3_reengage": (
                "Stage day_3_reengage: reopen the contact gently after a few days. "
                "A soft callback to the last theme works well."
            ),
            "day_7_reset": (
                "Stage day_7_reset: offer a simple weekly reset or a short emotional check-in. "
                "Make replying feel effortless."
            ),
            "day_14_reopen": (
                "Stage day_14_reopen: use the easiest possible entry point. "
                "One calm line and a very low-friction invitation back is enough."
            ),
        }
        return guidance.get(stage, guidance["day_1_checkin"])

    def _extract_name_hint(self, identity_facts: list[str]) -> str:
        for fact in identity_facts:
            normalized = str(fact or "").strip()
            prefix = "пользователя зовут "
            lowered = normalized.lower()
            if lowered.startswith(prefix):
                return normalized[len(prefix):].strip()
        return ""

    def _build_reengagement_starter_guidance(self, starter_family: str, *, active_mode: str) -> str:
        mode_note = ""
        if active_mode in {"night", "dominant"}:
            mode_note = "Keep the phrasing denser and more collected, but never theatrical."
        elif active_mode == "comfort":
            mode_note = "Keep the tone softer and simpler, with no extra push."

        templates = {
            "soft_presence": (
                "Starter family soft_presence: open like a sudden warm thought about the person, without grand drama. "
                "Rhythm: one warm line, then one light question."
            ),
            "callback_thread": (
                "Starter family callback_thread: lightly reopen an earlier thread, but do not sound like a reminder bot. "
                "Hint at the thread and leave room for an answer."
            ),
            "mood_ping": (
                "Starter family mood_ping: begin with a small feeling or observation, like you are naturally checking in. "
                "Quiet, alive, and unforced works best."
            ),
            "playful_hook": (
                "Starter family playful_hook: add a little spark or crooked hook, but no clowning and no pressure. "
                "It should make replying feel immediate."
            ),
        }
        base = templates.get(starter_family, templates["soft_presence"])
        return f"{base} {mode_note}".strip()

    def _hours_since(self, value: str) -> float:
        parsed = self._parse_iso(value)
        if parsed is None:
            return 10**6
        return (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0

    def _parse_iso(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
