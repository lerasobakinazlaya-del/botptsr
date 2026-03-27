import asyncio
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from services.telegram_formatting import (
    TelegramFormattingOptions,
    escape_plain_text_for_telegram,
    format_model_response_for_telegram,
)


logger = logging.getLogger(__name__)


class ProactiveMessageService:
    def __init__(
        self,
        *,
        client,
        message_repository,
        proactive_repository,
        user_preference_repository,
        state_repository,
        long_term_memory_service,
        keyword_memory_service,
        prompt_builder,
        access_engine,
        settings_service,
        user_service,
    ):
        self.client = client
        self.message_repository = message_repository
        self.proactive_repository = proactive_repository
        self.user_preference_repository = user_preference_repository
        self.state_repository = state_repository
        self.long_term_memory_service = long_term_memory_service
        self.keyword_memory_service = keyword_memory_service
        self.prompt_builder = prompt_builder
        self.access_engine = access_engine
        self.settings_service = settings_service
        self.user_service = user_service

        self._task: asyncio.Task | None = None
        self._bot: Bot | None = None

    async def start(self, bot: Bot) -> None:
        if self._task is not None:
            return

        self._bot = bot
        self._task = asyncio.create_task(
            self._run_loop(),
            name="proactive-message-loop",
        )

    async def close(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self._bot = None

    async def _run_loop(self) -> None:
        while True:
            settings = self._get_settings()
            try:
                if settings["enabled"]:
                    await self._tick(settings)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[PROACTIVE] Background proactive cycle failed")

            await asyncio.sleep(settings["scan_interval_seconds"])

    async def _tick(self, settings: dict[str, Any]) -> None:
        if self._bot is None:
            return

        candidates = await self.message_repository.get_inactive_user_candidates(
            min_inactive_hours=settings["min_inactive_hours"],
            max_inactive_days=settings["max_inactive_days"],
            min_user_messages=settings["min_user_messages"],
            limit=settings["candidate_batch_size"],
        )
        if not candidates:
            return

        sent_count = 0
        for candidate in candidates:
            if sent_count >= settings["max_messages_per_cycle"]:
                break

            if not await self._is_eligible(candidate, settings):
                continue

            message_text = await self._generate_message(candidate, settings)
            if not message_text:
                continue

            sent = await self._deliver_message(candidate, message_text)
            if sent:
                sent_count += 1

            delay_seconds = float(settings["per_message_delay_seconds"])
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

    async def _is_eligible(
        self,
        candidate: dict[str, Any],
        settings: dict[str, Any],
    ) -> bool:
        user_id = int(candidate["user_id"])
        user = await self.user_service.get_user(user_id)
        if user is None or bool(user.get("is_admin")):
            return False

        state = await self.state_repository.get(user_id)
        candidate["state_snapshot"] = state
        if candidate.get("last_message_role") != "assistant":
            return False

        last_user_message_at = candidate.get("last_user_message_at")
        if not last_user_message_at:
            return False

        proactive_preferences = await self.user_preference_repository.get_preferences(
            user_id,
            fallback=state.get("proactive_preferences"),
        )

        if not bool(proactive_preferences.get("proactive_enabled", True)):
            return False

        if self._is_in_quiet_hours(
            settings,
            timezone_name=str(proactive_preferences.get("timezone") or "").strip() or None,
        ):
            return False

        if int(state.get("interaction_count", 0) or 0) < int(settings["min_interaction_count"]):
            return False

        if float(state.get("interest", 0.0) or 0.0) < float(settings["min_interest"]):
            return False

        if float(state.get("irritation", 0.0) or 0.0) > float(settings["max_irritation"]):
            return False

        if float(state.get("fatigue", 0.0) or 0.0) > float(settings["max_fatigue"]):
            return False

        if str(state.get("emotional_tone") or "").strip() in {"overwhelmed", "anxious", "guarded"}:
            return False

        if await self.proactive_repository.has_event_for_silence(
            user_id=user_id,
            source_last_user_message_at=last_user_message_at,
        ):
            return False

        if await self.proactive_repository.has_recent_event(
            user_id=user_id,
            cooldown_hours=settings["cooldown_hours"],
        ):
            return False

        return True

    async def _generate_message(
        self,
        candidate: dict[str, Any],
        settings: dict[str, Any],
    ) -> str:
        user_id = int(candidate["user_id"])
        state = candidate.get("state_snapshot") or await self.state_repository.get(user_id)
        access_level = self.access_engine.update_access_level(state)
        active_mode = str(state.get("active_mode") or "base")
        history = await self.message_repository.get_last_messages(
            user_id=user_id,
            limit=settings["history_limit"],
        )

        durable_memory = await self.long_term_memory_service.build_prompt_context(user_id)
        state_memory = self.keyword_memory_service.build_prompt_context(state, history=history)
        memory_context = "\n".join(
            part.strip()
            for part in (durable_memory, state_memory)
            if part and part.strip()
        )
        transcript = self._build_transcript(history)

        base_prompt = self.prompt_builder.build_system_prompt(
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            memory_context=memory_context,
            user_message="",
        )
        proactive_prompt = (
            "You are sending a proactive follow-up after a pause in the conversation.\n"
            "This is not a reply to a new incoming message.\n"
            "Write one short natural Telegram message in Russian.\n"
            "Use memory only if it feels organic and non-creepy.\n"
            "Never mention logs, tracking, stored memory, inactivity timers, or that you decided to message first.\n"
            "Do not guilt the user for silence.\n"
            "Keep it warm, light, and easy to ignore.\n"
            "Ask at most one simple question.\n"
            "Maximum length: 320 characters.\n"
            "Return only the final message text."
        )
        user_prompt = (
            f"Recent dialogue:\n{transcript or 'No recent dialogue'}\n\n"
            f"Useful memory:\n{memory_context or 'No stable memory'}\n\n"
            "Write a gentle follow-up that feels consistent with the relationship."
        )

        text, _tokens_used = await self.client.generate(
            messages=[
                {"role": "system", "content": base_prompt},
                {"role": "system", "content": proactive_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=str(settings.get("model") or self._get_ai_settings().get("openai_model") or self.client.model),
            temperature=float(settings["temperature"]),
            max_completion_tokens=int(settings["max_completion_tokens"]),
            reasoning_effort=str(settings.get("reasoning_effort") or "").strip() or None,
            verbosity="low",
            user=f"{user_id}:proactive",
        )
        return self._clean_generated_text(text)

    async def _deliver_message(
        self,
        candidate: dict[str, Any],
        message_text: str,
    ) -> bool:
        if self._bot is None:
            return False

        user_id = int(candidate["user_id"])
        state = await self.state_repository.get(user_id)
        active_mode = str(state.get("active_mode") or "base")
        mode_config = self.settings_service.get_modes().get(active_mode, {})
        formatting_options = TelegramFormattingOptions(
            allow_bold=bool(mode_config.get("allow_bold", False)),
            allow_italic=bool(mode_config.get("allow_italic", False)),
        )
        formatted = format_model_response_for_telegram(message_text, formatting_options)
        last_user_message_at = candidate.get("last_user_message_at")

        try:
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text=formatted or escape_plain_text_for_telegram(message_text),
                )
            except TelegramBadRequest:
                logger.exception("[PROACTIVE] Formatting fallback for user_id=%s", user_id)
                await self._bot.send_message(
                    chat_id=user_id,
                    text=escape_plain_text_for_telegram(message_text),
                )

            await self.message_repository.save(user_id, "assistant", message_text)
            await self.proactive_repository.log_event(
                user_id=user_id,
                trigger_kind="inactivity_followup",
                status="sent",
                source_last_user_message_at=last_user_message_at,
            )
            logger.info("[PROACTIVE] Sent follow-up to user_id=%s", user_id)
            return True
        except TelegramForbiddenError as exc:
            logger.warning("[PROACTIVE] Forbidden for user_id=%s: %s", user_id, exc)
            await self.proactive_repository.log_event(
                user_id=user_id,
                trigger_kind="inactivity_followup",
                status="failed",
                source_last_user_message_at=last_user_message_at,
                error_text=str(exc),
            )
            return False
        except Exception as exc:
            logger.exception("[PROACTIVE] Failed to send follow-up to user_id=%s", user_id)
            await self.proactive_repository.log_event(
                user_id=user_id,
                trigger_kind="inactivity_followup",
                status="failed",
                source_last_user_message_at=last_user_message_at,
                error_text=str(exc),
            )
            return False

    def _build_transcript(self, history: list[Any]) -> str:
        lines: list[str] = []
        for message in history[-8:]:
            role = getattr(message, "role", "")
            if role not in {"user", "assistant"}:
                continue

            content = " ".join(str(getattr(message, "content", "")).split()).strip()
            if not content:
                continue

            role_label = "user" if role == "user" else "lira"
            lines.append(f"{role_label}: {content[:220]}")

        return "\n".join(lines)

    def _clean_generated_text(self, text: str) -> str:
        cleaned = " ".join((text or "").split()).strip()
        return cleaned[:320]

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

    def _get_settings(self) -> dict[str, Any]:
        runtime = self.settings_service.get_runtime_settings()
        return runtime["proactive"]

    def _get_ai_settings(self) -> dict[str, Any]:
        runtime = self.settings_service.get_runtime_settings()
        return runtime["ai"]
