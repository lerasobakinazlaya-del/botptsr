from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryCategory:
    key: str
    label: str
    prompt_limit: int


class MemoryProfileService:
    CACHE_TTL_SECONDS = 900
    CACHE_PREFIX = "bot:memory-profile:v2"

    CATEGORIES: tuple[MemoryCategory, ...] = (
        MemoryCategory("identity_facts", "Важные имена и связи", 4),
        MemoryCategory("goals", "Цели и желания", 3),
        MemoryCategory("interests", "Интересы и живые темы", 3),
        MemoryCategory("personality_traits", "Устойчивые черты", 2),
        MemoryCategory("response_preferences", "Как лучше отвечать этому пользователю", 2),
        MemoryCategory("support_preferences", "Как лучше откликаться пользователю", 2),
        MemoryCategory("coping_tools", "Что обычно помогает", 2),
        MemoryCategory("triggers", "Что лучше не задевать", 2),
        MemoryCategory("symptoms", "Повторяющиеся симптомы или перегруз", 2),
        MemoryCategory("important_context", "Важный жизненный контекст", 2),
        MemoryCategory("current_focus", "Что сейчас особенно живо", 2),
        MemoryCategory("open_loops", "Незавершенные темы", 2),
        MemoryCategory("recurring_topics", "Повторяющиеся темы", 2),
        MemoryCategory("recent_topics", "Недавние темы", 2),
        MemoryCategory("shared_threads", "Нити прошлых разговоров", 2),
        MemoryCategory("callback_candidates", "Что можно мягко вспомнить позже", 2),
        MemoryCategory("recent_thread", "Последняя живая нить разговора", 1),
    )

    def __init__(
        self,
        *,
        long_term_memory_service,
        redis=None,
    ):
        self.long_term_memory_service = long_term_memory_service
        self.redis = redis

    async def build_prompt_context(
        self,
        *,
        user_id: int,
        state: dict[str, Any],
        history: list[Any] | None = None,
    ) -> str:
        long_term_memories = await self._get_long_term_memories(user_id)
        fingerprint = self._build_fingerprint(
            user_id=user_id,
            state=state,
            history=history or [],
            long_term_memories=long_term_memories,
        )
        cache_key = f"{self.CACHE_PREFIX}:{user_id}:{fingerprint}"

        cached = await self._cache_get(cache_key)
        if cached is not None:
            return cached

        profile = self._build_profile(
            state=state,
            history=history or [],
            long_term_memories=long_term_memories,
        )
        rendered = self._render_profile(profile)
        await self._cache_set(cache_key, rendered)
        return rendered

    def get_category_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "key": category.key,
                "label": category.label,
                "prompt_limit": category.prompt_limit,
            }
            for category in self.CATEGORIES
        ]

    async def _get_long_term_memories(self, user_id: int) -> list[dict[str, Any]]:
        if self.long_term_memory_service is None:
            return []
        if not hasattr(self.long_term_memory_service, "get_user_memories"):
            return []
        try:
            return await self.long_term_memory_service.get_user_memories(user_id, limit=80)
        except Exception:
            return []

    def _build_profile(
        self,
        *,
        state: dict[str, Any],
        history: list[Any],
        long_term_memories: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        profile: dict[str, list[str]] = {category.key: [] for category in self.CATEGORIES}

        user_profile = state.get("user_profile") if isinstance(state.get("user_profile"), dict) else {}
        memory_flags = state.get("memory_flags") if isinstance(state.get("memory_flags"), dict) else {}
        support_profile = (
            memory_flags.get("support_profile")
            if isinstance(memory_flags.get("support_profile"), dict)
            else {}
        )
        relationship_state = (
            state.get("relationship_state")
            if isinstance(state.get("relationship_state"), dict)
            else {}
        )

        for key in ("identity_facts", "goals", "interests", "personality_traits", "recurring_topics"):
            self._merge_values(profile, key, user_profile.get(key))

        for key in ("current_focus", "open_loops", "recent_topics"):
            self._merge_memory_items(profile, key, memory_flags.get(key))

        for key in ("support_preferences", "coping_tools", "triggers", "symptoms", "important_context"):
            self._merge_memory_items(profile, key, support_profile.get(key))

        self._merge_values(
            profile,
            "response_preferences",
            self._render_response_preferences(relationship_state.get("response_preferences")),
        )
        self._merge_values(profile, "shared_threads", relationship_state.get("shared_threads"))
        self._merge_values(profile, "callback_candidates", relationship_state.get("callback_candidates"))
        self._merge_values(profile, "recent_thread", self._build_recent_thread(history))

        for memory in long_term_memories:
            category = str(memory.get("category") or "").strip()
            if category not in profile:
                continue
            self._merge_values(profile, category, memory.get("value"))

        return profile

    def _render_profile(self, profile: dict[str, list[str]]) -> str:
        lines: list[str] = []
        for category in self.CATEGORIES:
            values = [value for value in profile.get(category.key, []) if value][: category.prompt_limit]
            if values:
                lines.append(f"- {category.label}: " + "; ".join(values))
        return "\n".join(lines)

    def _build_recent_thread(self, history: list[Any]) -> str:
        snippets: list[str] = []
        for message in reversed(history):
            role = getattr(message, "role", None)
            if role != "user":
                continue
            content = " ".join(str(getattr(message, "content", "")).split()).strip()
            if len(content) < 16:
                continue
            snippet = content[:140]
            if snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= 2:
                break
        snippets.reverse()
        return " | ".join(snippets)

    def _render_response_preferences(self, raw: Any) -> list[str]:
        preferences = raw if isinstance(raw, dict) else {}
        fragments: list[str] = []
        if preferences.get("length") == "brief":
            fragments.append("предпочитает ответы короче")
        if preferences.get("length") == "detailed":
            fragments.append("любит более развернутые ответы")
        if preferences.get("initiative") == "high":
            fragments.append("инициатива от тебя уместна")
        if preferences.get("questions") == "welcome":
            fragments.append("уточняющий вопрос допустим")
        return fragments

    def _merge_memory_items(
        self,
        profile: dict[str, list[str]],
        key: str,
        raw_items: Any,
    ) -> None:
        if not isinstance(raw_items, list):
            return
        values: list[str] = []
        for item in raw_items:
            if isinstance(item, dict):
                value = str(item.get("value") or "").strip()
            else:
                value = str(item or "").strip()
            if value:
                values.append(value)
        self._merge_values(profile, key, values)

    def _merge_values(
        self,
        profile: dict[str, list[str]],
        key: str,
        raw_values: Any,
    ) -> None:
        if key not in profile:
            return
        if raw_values in (None, "", []):
            return
        if isinstance(raw_values, str):
            values = [raw_values]
        else:
            values = list(raw_values)

        existing = list(profile.get(key) or [])
        seen = {value.casefold(): value for value in existing}
        for raw_value in values:
            value = " ".join(str(raw_value or "").split()).strip()
            if not value:
                continue
            normalized = value.casefold()
            if normalized in seen:
                continue
            seen[normalized] = value
            existing.append(value)
        profile[key] = existing

    def _build_fingerprint(
        self,
        *,
        user_id: int,
        state: dict[str, Any],
        history: list[Any],
        long_term_memories: list[dict[str, Any]],
    ) -> str:
        state_payload = {
            "user_profile": state.get("user_profile", {}),
            "memory_flags": state.get("memory_flags", {}),
            "relationship_state": {
                "response_preferences": ((state.get("relationship_state") or {}).get("response_preferences")),
                "shared_threads": ((state.get("relationship_state") or {}).get("shared_threads")),
                "callback_candidates": ((state.get("relationship_state") or {}).get("callback_candidates")),
            },
        }
        history_payload = [
            {
                "role": getattr(item, "role", ""),
                "content": " ".join(str(getattr(item, "content", "")).split()).strip()[:160],
            }
            for item in history[-6:]
        ]
        long_term_payload = [
            {
                "id": memory.get("id"),
                "category": memory.get("category"),
                "value": memory.get("value"),
                "updated_at": memory.get("updated_at"),
                "times_seen": memory.get("times_seen"),
                "pinned": memory.get("pinned"),
            }
            for memory in long_term_memories
        ]
        blob = json.dumps(
            {
                "user_id": user_id,
                "state": state_payload,
                "history": history_payload,
                "long_term": long_term_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    async def _cache_get(self, key: str) -> str | None:
        if self.redis is None:
            return None
        try:
            payload = await self.redis.get(key)
        except Exception:
            return None
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="ignore")
        return str(payload)

    async def _cache_set(self, key: str, value: str) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.set(key, value, ex=self.CACHE_TTL_SECONDS)
        except Exception:
            return
