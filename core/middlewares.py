import logging
import re
import time

from aiogram import BaseMiddleware
from aiogram.types import Message


LOGGER = logging.getLogger(__name__)
URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)


class LoggingMiddleware(BaseMiddleware):
    def __init__(self, preview_length: int = 120):
        self.preview_length = preview_length

    async def __call__(self, handler, event, data):
        try:
            if isinstance(event, Message) and event.from_user:
                LOGGER.info(
                    "[MSG] user_id=%s username=%s length=%s preview=%r",
                    event.from_user.id,
                    event.from_user.username,
                    len(event.text or ""),
                    self._build_preview(event.text),
                )
            return await handler(event, data)
        except Exception as exc:
            LOGGER.exception("[ERROR] Unhandled exception: %s", exc)
            raise

    def _build_preview(self, text: str | None) -> str:
        if not text:
            return ""

        normalized = " ".join(text.split())
        if len(normalized) <= self.preview_length:
            return normalized
        return normalized[: self.preview_length - 3] + "..."


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, redis, settings_service):
        self.redis = redis
        self.settings_service = settings_service
        self._local_throttle_until: dict[int, float] = {}
        self._local_warning_until: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            safety = self.settings_service.get_runtime_settings()["safety"]
            allowed = await self._is_allowed(
                user_id=user_id,
                rate_limit_seconds=float(safety["throttle_rate_limit_seconds"]),
            )

            if not allowed:
                should_warn = await self._should_warn(
                    user_id=user_id,
                    warning_interval_seconds=float(safety["throttle_warning_interval_seconds"]),
                )

                if should_warn:
                    await event.answer(safety["throttle_warning_text"])

                return

        return await handler(event, data)

    async def _is_allowed(self, user_id: int, rate_limit_seconds: float) -> bool:
        rate_limit_ms = max(1, int(rate_limit_seconds * 1000))

        if self.redis is None:
            now = time.time() * 1000
            expires_at = self._local_throttle_until.get(user_id, 0)
            if expires_at > now:
                return False
            self._local_throttle_until[user_id] = now + rate_limit_ms
            return True

        throttle_key = f"throttle:user:{user_id}"
        return bool(
            await self.redis.set(
                throttle_key,
                str(time.time()),
                px=rate_limit_ms,
                nx=True,
            )
        )

    async def _should_warn(self, user_id: int, warning_interval_seconds: float) -> bool:
        warning_interval_ms = max(1, int(warning_interval_seconds * 1000))

        if self.redis is None:
            now = time.time() * 1000
            expires_at = self._local_warning_until.get(user_id, 0)
            if expires_at > now:
                return False
            self._local_warning_until[user_id] = now + warning_interval_ms
            return True

        warning_key = f"throttle-warning:user:{user_id}"
        return bool(
            await self.redis.set(
                warning_key,
                "1",
                px=warning_interval_ms,
                nx=True,
            )
        )


class MessageSizeMiddleware(BaseMiddleware):
    def __init__(self, settings_service):
        self.settings_service = settings_service

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text:
            safety = self.settings_service.get_runtime_settings()["safety"]
            if len(event.text) > int(safety["max_message_length"]):
                await event.answer(safety["message_too_long_text"])
                return

        return await handler(event, data)


class SuspiciousContentMiddleware(BaseMiddleware):
    def __init__(self, settings_service):
        self.settings_service = settings_service

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text:
            safety = self.settings_service.get_runtime_settings()["safety"]
            if not safety["reject_suspicious_messages"]:
                return await handler(event, data)

            text = event.text.strip()
            keywords = [
                keyword.lower()
                for keyword in safety["suspicious_keywords"]
                if str(keyword).strip()
            ]
            has_link = bool(URL_PATTERN.search(text))
            lowered = text.lower()
            has_suspicious_keyword = any(keyword in lowered for keyword in keywords)

            if has_link and has_suspicious_keyword:
                LOGGER.warning(
                    "[SUSPICIOUS] user_id=%s preview=%r",
                    event.from_user.id if event.from_user else None,
                    text[:120],
                )
                await event.answer(safety["suspicious_rejection_text"])
                return

        return await handler(event, data)
