from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from services.prompt_safety import sanitize_memory_value


class LongTermMemoryService:
    CATEGORY_WEIGHTS = {
        "goals": 2.8,
        "interests": 2.2,
        "personality_traits": 2.0,
        "support_preferences": 4.0,
        "coping_tools": 3.6,
        "triggers": 4.2,
        "symptoms": 3.4,
        "important_context": 4.5,
        "current_focus": 1.6,
        "open_loops": 2.4,
        "recent_topics": 1.3,
        "summary_recent_arc": 2.1,
        "summary_emotional_direction": 2.0,
        "summary_open_loops": 2.3,
        "summary_response_hint": 1.7,
    }

    CATEGORY_LIMITS = {
        "goals": 3,
        "interests": 4,
        "personality_traits": 3,
        "support_preferences": 3,
        "coping_tools": 3,
        "triggers": 3,
        "symptoms": 3,
        "important_context": 3,
        "current_focus": 3,
        "open_loops": 4,
        "recent_topics": 4,
        "summary_recent_arc": 1,
        "summary_emotional_direction": 1,
        "summary_open_loops": 1,
        "summary_response_hint": 1,
    }

    CATEGORY_DECAY_PER_DAY = {
        "goals": 0.01,
        "interests": 0.01,
        "personality_traits": 0.015,
        "support_preferences": 0.01,
        "coping_tools": 0.015,
        "triggers": 0.008,
        "symptoms": 0.015,
        "important_context": 0.005,
        "current_focus": 0.25,
        "open_loops": 0.12,
        "recent_topics": 0.18,
        "summary_recent_arc": 0.06,
        "summary_emotional_direction": 0.05,
        "summary_open_loops": 0.08,
        "summary_response_hint": 0.16,
    }

    CATEGORY_LABELS = {
        "goals": "Долгосрочные цели",
        "interests": "Устойчивые интересы",
        "personality_traits": "Устойчивые черты",
        "support_preferences": "Как лучше откликаться пользователю",
        "coping_tools": "Что обычно помогает",
        "triggers": "Известные триггеры",
        "symptoms": "Повторяющиеся симптомы или паттерны перегруза",
        "important_context": "Важный жизненный контекст",
        "current_focus": "Что сейчас особенно живо",
        "open_loops": "Открытые петли и незавершенные темы",
        "recent_topics": "Повторяющиеся недавние темы",
        "summary_recent_arc": "Длиннее эмоциональная дуга",
        "summary_emotional_direction": "Эмоциональное направление",
        "summary_open_loops": "Незавершенная нить из сводок",
        "summary_response_hint": "Какой ответ обычно подходит дальше",
    }

    PROMPT_CATEGORY_LIMITS = {
        "goals": 2,
        "interests": 3,
        "personality_traits": 2,
        "support_preferences": 2,
        "coping_tools": 2,
        "triggers": 2,
        "symptoms": 2,
        "important_context": 2,
        "current_focus": 2,
        "open_loops": 2,
        "recent_topics": 2,
        "summary_recent_arc": 1,
        "summary_emotional_direction": 1,
        "summary_open_loops": 1,
        "summary_response_hint": 1,
    }

    CATEGORY_PRUNE_AFTER_DAYS = {
        "goals": 120,
        "interests": 120,
        "personality_traits": 120,
        "support_preferences": 90,
        "coping_tools": 75,
        "triggers": 120,
        "symptoms": 60,
        "important_context": 180,
        "current_focus": 7,
        "open_loops": 30,
        "recent_topics": 14,
        "summary_recent_arc": 30,
        "summary_emotional_direction": 30,
        "summary_open_loops": 45,
        "summary_response_hint": 21,
    }

    CATEGORY_PRUNE_MIN_SCORE = {
        "goals": 0.4,
        "interests": 0.4,
        "personality_traits": 0.45,
        "support_preferences": 0.6,
        "coping_tools": 0.6,
        "triggers": 0.7,
        "symptoms": 0.55,
        "important_context": 0.65,
        "current_focus": 0.9,
        "open_loops": 0.7,
        "recent_topics": 0.75,
        "summary_recent_arc": 0.65,
        "summary_emotional_direction": 0.6,
        "summary_open_loops": 0.7,
        "summary_response_hint": 0.8,
    }

    def __init__(
        self,
        repository,
        keyword_memory_service,
        settings_service,
    ):
        self.repository = repository
        self.keyword_memory_service = keyword_memory_service
        self.settings_service = settings_service

    async def init_table(self) -> None:
        await self.repository.init_table()

    def is_enabled(self) -> bool:
        ai_settings = self.settings_service.get_runtime_settings()["ai"]
        return bool(ai_settings.get("long_term_memory_enabled", True))

    async def capture_from_message(self, user_id: int, message_text: str) -> None:
        if not self.is_enabled():
            return

        candidates = self.keyword_memory_service.extract_memory_candidates(message_text)
        has_updates = await self._store_candidates(user_id, candidates, source_kind="message")
        if has_updates:
            await self.auto_prune(user_id)

    async def capture_summary(self, user_id: int, summary: dict[str, Any]) -> None:
        if not self.is_enabled() or not isinstance(summary, dict):
            return

        summary_candidates = {
            "summary_recent_arc": [summary.get("recent_arc")],
            "summary_emotional_direction": [summary.get("emotional_direction")],
            "summary_open_loops": [summary.get("open_loops")],
            "summary_response_hint": [summary.get("response_hint")],
        }
        has_updates = await self._store_candidates(user_id, summary_candidates, source_kind="summary")
        if has_updates:
            await self.auto_prune(user_id)

    async def get_user_memories(
        self,
        user_id: int,
        *,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled():
            return []
        memories = await self.repository.get_user_memories(user_id, limit=limit)
        scored = [memory | {"score": round(self._score_memory(memory), 3)} for memory in memories]
        scored.sort(key=lambda item: (-int(bool(item.get("pinned"))), -float(item.get("score", 0.0)), -float(item.get("weight", 0.0))))
        return scored

    async def build_prompt_context(self, user_id: int) -> str:
        if not self.is_enabled():
            return ""

        ai_settings = self.settings_service.get_runtime_settings()["ai"]
        raw_memories = await self.repository.get_user_memories(
            user_id,
            limit=max(10, int(ai_settings.get("long_term_memory_max_items", 12)) * 3),
        )
        if not raw_memories:
            return ""

        memories = sorted(
            raw_memories,
            key=lambda item: (
                -int(bool(item.get("pinned"))),
                -self._score_memory(item),
                -float(item.get("weight", 0.0)),
            ),
        )

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        selected_ids: list[int] = []

        for memory in memories:
            category = str(memory.get("category") or "")
            if category not in self.PROMPT_CATEGORY_LIMITS:
                continue
            if len(grouped[category]) >= self.PROMPT_CATEGORY_LIMITS[category]:
                continue
            grouped[category].append(memory)
            selected_ids.append(int(memory["id"]))

        lines: list[str] = []
        for category, label in self.CATEGORY_LABELS.items():
            items = grouped.get(category) or []
            values = [item["value"] for item in items if item.get("value")]
            if values:
                lines.append(f"- {label}: " + "; ".join(values))

        if selected_ids:
            await self.repository.mark_used(selected_ids)

        return "\n".join(lines)

    async def set_pinned(self, memory_id: int, value: bool) -> None:
        await self.repository.set_pinned(memory_id, value)

    async def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        memory = await self.repository.get_memory(memory_id)
        if memory is None:
            return None
        return memory | {"score": round(self._score_memory(memory), 3)}

    async def save_manual_memory(
        self,
        *,
        user_id: int,
        category: str,
        value: str,
        weight: float | None = None,
        pinned: bool = False,
        memory_id: int | None = None,
    ) -> dict[str, Any]:
        normalized_category = self._normalize_category(category)
        normalized_weight = self._normalize_weight(
            weight,
            category=normalized_category,
        )
        if memory_id is None:
            memory = await self.repository.create_memory(
                user_id=user_id,
                category=normalized_category,
                value=value,
                weight=normalized_weight,
                source_kind="manual",
                pinned=pinned,
            )
        else:
            memory = await self.repository.update_memory(
                memory_id=memory_id,
                category=normalized_category,
                value=value,
                weight=normalized_weight,
                pinned=pinned,
                source_kind="manual",
            )
            if memory is None:
                raise ValueError("Memory not found")
        return memory | {"score": round(self._score_memory(memory), 3)}

    async def delete_memory(self, memory_id: int) -> bool:
        return await self.repository.delete_memory(memory_id)

    async def auto_prune(self, user_id: int) -> dict[str, Any]:
        ai_settings = self.settings_service.get_runtime_settings()["ai"]
        if not self.is_enabled() or not bool(ai_settings.get("long_term_memory_auto_prune_enabled", True)):
            return {"deleted_count": 0, "kept_count": 0, "soft_limit": int(ai_settings.get("long_term_memory_soft_limit", 60))}

        soft_limit = max(12, int(ai_settings.get("long_term_memory_soft_limit", 60)))
        memories = await self.repository.get_user_memories(
            user_id,
            limit=max(soft_limit * 4, 240),
        )
        if not memories:
            return {"deleted_count": 0, "kept_count": 0, "soft_limit": soft_limit}

        scored_memories = [
            memory | {"score": self._score_memory(memory)}
            for memory in memories
        ]
        to_delete: set[int] = set()

        for memory in scored_memories:
            if memory.get("pinned"):
                continue
            category = str(memory.get("category") or "")
            freshness_days = self._days_since(memory.get("updated_at")) or self._days_since(memory.get("created_at"))
            if (
                freshness_days >= float(self.CATEGORY_PRUNE_AFTER_DAYS.get(category, 45))
                and float(memory.get("score", 0.0)) <= float(self.CATEGORY_PRUNE_MIN_SCORE.get(category, 0.5))
            ):
                to_delete.add(int(memory["id"]))

        remaining = [
            memory
            for memory in scored_memories
            if int(memory["id"]) not in to_delete
        ]
        unpinned_remaining = [memory for memory in remaining if not memory.get("pinned")]

        if len(unpinned_remaining) > soft_limit:
            overflow = len(unpinned_remaining) - soft_limit
            trim_candidates = sorted(
                unpinned_remaining,
                key=lambda item: (
                    float(item.get("score", 0.0)),
                    self._days_since(item.get("updated_at")),
                    self._days_since(item.get("last_used_at")),
                    int(item.get("times_seen", 0)),
                ),
                reverse=False,
            )
            for memory in trim_candidates[:overflow]:
                to_delete.add(int(memory["id"]))

        deleted_count = await self.repository.delete_memories(sorted(to_delete))
        kept_count = max(0, len(memories) - deleted_count)
        return {
            "deleted_count": deleted_count,
            "kept_count": kept_count,
            "soft_limit": soft_limit,
        }

    def get_category_options(self) -> list[dict[str, str]]:
        return [
            {"key": key, "label": label}
            for key, label in self.CATEGORY_LABELS.items()
        ]

    async def _store_candidates(
        self,
        user_id: int,
        candidates: dict[str, list[str | None]],
        *,
        source_kind: str,
    ) -> bool:
        has_updates = False
        for category, values in candidates.items():
            if category not in self.CATEGORY_WEIGHTS:
                continue

            seen_values: set[str] = set()
            for value in values or []:
                cleaned_value = sanitize_memory_value(value, max_chars=220)
                if not cleaned_value:
                    continue

                normalized_value = cleaned_value.casefold()
                if normalized_value in seen_values:
                    continue
                seen_values.add(normalized_value)

                await self.repository.upsert(
                    user_id=user_id,
                    category=category,
                    value=cleaned_value,
                    weight=self.CATEGORY_WEIGHTS[category],
                    source_kind=source_kind,
                    commit=False,
                )
                has_updates = True

        if has_updates:
            await self.repository.commit()
        return has_updates

    def _score_memory(self, memory: dict[str, Any]) -> float:
        if memory.get("pinned"):
            return 10_000.0 + float(memory.get("weight", 0.0))

        category = str(memory.get("category") or "")
        decay_per_day = float(self.CATEGORY_DECAY_PER_DAY.get(category, 0.05))
        base_weight = float(memory.get("weight", 0.0))
        repetition_bonus = min(2.0, float(memory.get("times_seen", 0)) * 0.2)
        freshness_days = self._days_since(memory.get("updated_at")) or self._days_since(memory.get("created_at"))
        used_days = self._days_since(memory.get("last_used_at"))
        inactivity_penalty = max(0.0, freshness_days * decay_per_day)
        used_penalty = max(0.0, used_days * decay_per_day * 0.35)
        return max(0.0, base_weight + repetition_bonus - inactivity_penalty - used_penalty)

    def _normalize_category(self, category: str) -> str:
        normalized = str(category or "").strip()
        if normalized not in self.CATEGORY_LABELS:
            raise ValueError("Unknown memory category")
        return normalized

    def _normalize_weight(self, weight: float | None, *, category: str) -> float:
        if weight in (None, ""):
            return float(self.CATEGORY_WEIGHTS[category])
        return max(0.1, min(25.0, float(weight)))

    def _days_since(self, raw_value: Any) -> float:
        parsed = self._parse_timestamp(raw_value)
        if parsed is None:
            return 365.0
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400.0)

    def _parse_timestamp(self, raw_value: Any) -> datetime | None:
        text = str(raw_value or "").strip()
        if not text:
            return None

        for parser in (
            lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
            lambda value: datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
        ):
            try:
                parsed = parser(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue

        return None
