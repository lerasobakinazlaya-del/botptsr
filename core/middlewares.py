import logging
import re
import time

from aiogram import BaseMiddleware
from aiogram.types import Message


LOGGER = logging.getLogger(__name__)
URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
CRYPTO_PATTERN = re.compile(r"\b(bitcoin|btc|casino|bet|airdrop)\b", re.IGNORECASE)


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
    def __init__(
        self,
        redis,
        rate_limit: float = 1.0,
        warning_interval: float = 5.0,
    ):
        self.redis = redis
        self.rate_limit_ms = max(1, int(rate_limit * 1000))
        self.warning_interval_ms = max(1, int(warning_interval * 1000))

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            throttle_key = f"throttle:user:{user_id}"
            warning_key = f"throttle-warning:user:{user_id}"

            allowed = await self.redis.set(
                throttle_key,
                str(time.time()),
                px=self.rate_limit_ms,
                nx=True,
            )

            if not allowed:
                should_warn = await self.redis.set(
                    warning_key,
                    "1",
                    px=self.warning_interval_ms,
                    nx=True,
                )

                if should_warn:
                    await event.answer("Too many requests. Please wait a moment.")

                return

        return await handler(event, data)


class MessageSizeMiddleware(BaseMiddleware):
    def __init__(self, max_length: int = 2000):
        self.max_length = max_length

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text and len(event.text) > self.max_length:
            await event.answer("Message is too long.")
            return

        return await handler(event, data)


class SuspiciousContentMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text:
            text = event.text.strip()

            has_link = bool(URL_PATTERN.search(text))
            has_crypto_spam = bool(CRYPTO_PATTERN.search(text))

            if has_link and has_crypto_spam:
                LOGGER.warning(
                    "[SUSPICIOUS] user_id=%s preview=%r",
                    event.from_user.id if event.from_user else None,
                    text[:120],
                )
                await event.answer("Message was rejected by the safety filter.")
                return

        return await handler(event, data)
