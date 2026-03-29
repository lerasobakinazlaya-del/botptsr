import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest

from services.telegram_formatting import (
    TelegramFormattingOptions,
    escape_plain_text_for_telegram,
    format_model_response_for_telegram,
)


logger = logging.getLogger(__name__)


class ReengagementService:
    BLOCKED_LAST_MOODS = {
        "тревога или внутреннее напряжение",
        "усталость или перегруз",
    }
    BLOCKED_EMOTIONAL_TONES = {"overwhelmed", "anxious", "guarded"}

    def __init__(
        self,
        *,
        ai_service,
        message_repository,
        state_repository,
        user_preference_repository,
        user_service,
        settings_service,
        db,
    ):
        self.ai_service = ai_service
        self.message_repository = message_repository
        self.state_repository = state_repository
        self.user_preference_repository = user_preference_repository
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
        if user is None or bool(user.get("is_admin")):
            return
        if str(candidate.get("last_message_role") or "").strip() not in {"", "assistant"}:
            logger.info("[REENGAGE] Skip user_id=%s reason=last_message_not_assistant", user_id)
            return

        runtime_settings = self.settings_service.get_runtime_settings()
        proactive_settings = runtime_settings["proactive"]
        ai_settings = runtime_settings["ai"]
        state = await self.state_repository.get(user_id)
        if str(state.get("emotional_tone") or "").strip() in self.BLOCKED_EMOTIONAL_TONES:
            logger.info("[REENGAGE] Skip user_id=%s reason=blocked_emotional_tone", user_id)
            return
        proactive_preferences = await self.user_preference_repository.get_preferences(
            user_id,
            fallback=state.get("proactive_preferences"),
        )
        if not bool(proactive_preferences.get("proactive_enabled", True)):
            logger.info("[REENGAGE] Skip user_id=%s reason=opted_out", user_id)
            return
        if self._is_in_quiet_hours(
            proactive_settings,
            timezone_name=str(proactive_preferences.get("timezone") or "").strip() or None,
        ):
            logger.info("[REENGAGE] Skip user_id=%s reason=quiet_hours", user_id)
            return

        relationship = dict(state.get("relationship_state") or {})
        last_user_message_at = relationship.get("last_user_message_at") or self._sqlite_to_iso(
            candidate.get("last_user_message_at")
        )
        relationship["last_user_message_at"] = last_user_message_at
        state["relationship_state"] = relationship
        if str(relationship.get("last_user_mood") or "").strip().lower() in self.BLOCKED_LAST_MOODS:
            logger.info("[REENGAGE] Skip user_id=%s reason=blocked_last_user_mood", user_id)
            return

        callback_context = self.ai_service.human_memory_service.get_reengagement_context(state)
        callback_topic = callback_context.get("callback_hint") or callback_context.get("topic") or ""
        if not self.ai_service.human_memory_service.can_send_reengagement(
            state,
            min_hours_between=settings["reengagement_min_hours_between"],
            last_user_message_at=last_user_message_at,
            callback_topic=callback_topic,
        ):
            return

        history_limit = ai_settings["history_message_limit"]
        history = await self.message_repository.get_last_messages(user_id=user_id, limit=history_limit)

        result = await self.ai_service.generate_reengagement(
            user_id=user_id,
            history=history,
            state=state,
        )

        response_mode = str(
            result.new_state.get("adaptive_mode")
            or result.new_state.get("active_mode")
            or state.get("active_mode")
            or "base"
        )
        mode_config = self.settings_service.get_modes().get(response_mode, {})
        formatting_options = TelegramFormattingOptions(
            allow_bold=bool(mode_config.get("allow_bold", False)),
            allow_italic=bool(mode_config.get("allow_italic", False)),
        )
        outbound_text = (
            format_model_response_for_telegram(result.response, formatting_options)
            or escape_plain_text_for_telegram(result.response)
        )

        try:
            try:
                await self._bot.send_message(user_id, outbound_text)
            except TelegramBadRequest:
                await self._bot.send_message(
                    user_id,
                    escape_plain_text_for_telegram(result.response),
                )
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

    def _is_in_quiet_hours(
        self,
        settings: dict[str, Any],
        *,
        timezone_name: str | None = None,
    ) -> bool:
        if not bool(settings.get("quiet_hours_enabled", True)):
            return False

        timezone_name = str(
            timezone_name
            or settings.get("timezone")
            or "Europe/Moscow"
        ).strip() or "Europe/Moscow"
        try:
            now_local = datetime.now(ZoneInfo(timezone_name))
        except Exception:
            now_local = datetime.now()

        start_hour = int(settings.get("quiet_hours_start", 0))
        end_hour = int(settings.get("quiet_hours_end", 8))
        current_hour = int(now_local.hour)

        if start_hour == end_hour:
            return False
        if start_hour < end_hour:
            return start_hour <= current_hour < end_hour
        return current_hour >= start_hour or current_hour < end_hour

    def _sqlite_to_iso(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc).isoformat()
