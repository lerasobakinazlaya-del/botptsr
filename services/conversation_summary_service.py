import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger(__name__)


class ConversationSummaryService:
    def __init__(
        self,
        client,
        message_repository,
        state_repository,
        settings_service,
        long_term_memory_service=None,
    ):
        self.client = client
        self.message_repository = message_repository
        self.state_repository = state_repository
        self.settings_service = settings_service
        self.long_term_memory_service = long_term_memory_service
        self._tasks: set[asyncio.Task] = set()

    def schedule_refresh(self, user_id: int, state_snapshot: dict[str, Any]) -> None:
        task = asyncio.create_task(
            self.maybe_refresh_summary(user_id, state_snapshot),
            name=f"summary-refresh-{user_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._log_task_error)

    async def maybe_refresh_summary(
        self,
        user_id: int,
        state_snapshot: dict[str, Any] | None = None,
    ) -> None:
        ai_settings = self.settings_service.get_runtime_settings()["ai"]
        if not ai_settings.get("episodic_summary_enabled", True):
            return

        state = state_snapshot or await self.state_repository.get(user_id)
        interaction_count = int(state.get("interaction_count", 0) or 0)
        min_interactions = int(ai_settings.get("episodic_summary_min_interactions", 4))
        if interaction_count < min_interactions:
            return

        memory_flags = dict(state.get("memory_flags") or {})
        meta = dict(memory_flags.get("episodic_summary_meta") or {})
        interval = int(ai_settings.get("episodic_summary_interval", 6))
        last_count = int(meta.get("interaction_count", 0) or 0)
        if interaction_count - last_count < interval:
            return

        history_limit = int(ai_settings.get("episodic_summary_history_limit", 18))
        history = await self.message_repository.get_last_messages(
            user_id=user_id,
            limit=history_limit,
        )
        transcript = self._build_transcript(history)
        if not transcript:
            return

        existing_summary = memory_flags.get("episodic_summary") or {}
        summary = await self._generate_summary(
            user_id=user_id,
            transcript=transcript,
            existing_summary=existing_summary,
            ai_settings=ai_settings,
        )
        if not summary:
            return

        latest_state = await self.state_repository.get(user_id)
        latest_flags = dict(latest_state.get("memory_flags") or {})
        latest_flags["episodic_summary"] = summary
        latest_flags["episodic_summary_meta"] = {
            "interaction_count": interaction_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "history_limit": history_limit,
        }
        latest_state["memory_flags"] = latest_flags
        await self.state_repository.save(user_id, latest_state)

        if self.long_term_memory_service is not None:
            await self.long_term_memory_service.capture_summary(user_id, summary)

        logger.debug(
            "[SUMMARY] Refreshed episodic summary for user_id=%s at interaction=%s",
            user_id,
            interaction_count,
        )

    async def _generate_summary(
        self,
        user_id: int,
        transcript: str,
        existing_summary: dict[str, Any],
        ai_settings: dict[str, Any],
    ) -> dict[str, str] | None:
        system_prompt = (
            "You compress a dialogue into short memory for a humanlike companion.\n"
            "Keep only context that should influence future replies for the next few turns.\n"
            "Preserve emotional continuity, unresolved topics, and what kind of response would fit next.\n"
            "Do not include generic advice, policy talk, or anything irrelevant.\n"
            "Return strict JSON with exactly these keys: recent_arc, emotional_direction, open_loops, response_hint.\n"
            "Each value must be in Russian, concise, and no longer than 180 characters."
        )
        user_prompt = (
            "Current summary:\n"
            f"{json.dumps(existing_summary, ensure_ascii=False)}\n\n"
            "Recent dialogue transcript:\n"
            f"{transcript}\n\n"
            "Update the summary."
        )

        text, _tokens_used = await self.client.generate(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=str(ai_settings.get("episodic_summary_model") or ai_settings.get("openai_model") or self.client.model),
            temperature=float(ai_settings.get("episodic_summary_temperature", 0.2)),
            max_completion_tokens=int(ai_settings.get("episodic_summary_max_tokens", 220)),
            reasoning_effort=str(ai_settings.get("episodic_summary_reasoning_effort") or "").strip() or None,
            verbosity=str(ai_settings.get("verbosity") or "").strip() or None,
            user=f"{user_id}:summary",
        )

        parsed = self._parse_summary_json(text)
        return parsed if parsed else None

    def _build_transcript(self, history: list[Any]) -> str:
        lines: list[str] = []
        for message in history:
            role = getattr(message, "role", "")
            if role not in {"user", "assistant"}:
                continue

            content = " ".join(str(getattr(message, "content", "")).split()).strip()
            if not content:
                continue

            role_label = "user" if role == "user" else "lira"
            lines.append(f"{role_label}: {content[:500]}")

        return "\n".join(lines[-18:])

    def _parse_summary_json(self, text: str) -> dict[str, str] | None:
        payload_text = text.strip()
        if not payload_text:
            return None

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            start = payload_text.find("{")
            end = payload_text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                payload = json.loads(payload_text[start : end + 1])
            except json.JSONDecodeError:
                return None

        if not isinstance(payload, dict):
            return None

        result: dict[str, str] = {}
        for key in ("recent_arc", "emotional_direction", "open_loops", "response_hint"):
            value = " ".join(str(payload.get(key, "")).split()).strip()
            result[key] = value[:180]

        if not any(result.values()):
            return None

        return result

    def _log_task_error(self, task: asyncio.Task) -> None:
        try:
            _result = task.result()
        except Exception:
            logger.exception("[SUMMARY] Background summary refresh failed")
