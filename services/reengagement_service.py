import asyncio
import logging
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger(__name__)


class ReengagementService:
    def __init__(
        self,
        *,
        ai_service,
        message_repository,
        state_repository,
        user_service,
        settings_service,
        db,
    ):
        self.ai_service = ai_service
        self.message_repository = message_repository
        self.state_repository = state_repository
        self.user_service = user_service
        self.settings_service = settings_service
        self.db = db
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._bot = None

    async def start(self, bot) -> None:
        if self._task is not None and not self._task.done():
            return

        self._bot = bot
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="reengagement-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            settings = self.settings_service.get_runtime_settings()["engagement"]
            poll_seconds = int(settings["reengagement_poll_seconds"])

            try:
                if settings["reengagement_enabled"]:
                    await self._run_once(settings)
            except Exception:
                logger.exception("Reengagement worker iteration failed")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                continue

    async def _run_once(self, settings: dict[str, Any]) -> None:
        candidates = await self.message_repository.get_reengagement_candidates(
            idle_hours=settings["reengagement_idle_hours"],
            recent_window_days=settings["reengagement_recent_window_days"],
            limit=settings["reengagement_batch_size"],
        )
        if not candidates:
            return

        for candidate in candidates:
            if self._stop_event.is_set():
                return
            await self._process_candidate(candidate, settings)

    async def _process_candidate(self, candidate: dict[str, Any], settings: dict[str, Any]) -> None:
        user_id = int(candidate["user_id"])
        user = await self.user_service.get_user(user_id)
        if user is None:
            return

        state = await self.state_repository.get(user_id)
        relationship = dict(state.get("relationship_state") or {})
        last_user_message_at = relationship.get("last_user_message_at") or self._sqlite_to_iso(
            candidate.get("last_user_message_at")
        )
        relationship["last_user_message_at"] = last_user_message_at
        state["relationship_state"] = relationship
        if not self.ai_service.human_memory_service.can_send_reengagement(
            state,
            min_hours_between=settings["reengagement_min_hours_between"],
            last_user_message_at=last_user_message_at,
        ):
            return

        history_limit = self.settings_service.get_runtime_settings()["ai"]["history_message_limit"]
        history = await self.message_repository.get_last_messages(user_id=user_id, limit=history_limit)

        result = await self.ai_service.generate_reengagement(
            user_id=user_id,
            history=history,
            state=state,
        )

        try:
            await self._bot.send_message(user_id, result.response)
        except Exception:
            logger.exception("Failed to send reengagement message to user %s", user_id)
            return

        try:
            async with self.db.transaction():
                await self.state_repository.save(user_id, result.new_state, commit=False)
                await self.message_repository.save(user_id, "assistant", result.response, commit=False)
        except Exception:
            logger.exception("Failed to persist reengagement message for user %s", user_id)
            return

        logger.info("[REENGAGE] sent proactive message to user_id=%s", user_id)

    def _sqlite_to_iso(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc).isoformat()
