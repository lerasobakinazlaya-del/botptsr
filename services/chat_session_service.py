import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator


class ChatSessionService:
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}
        self._active_sessions = 0
        self._wait_events = 0
        self._last_wait_ms = 0.0
        self._max_wait_ms = 0.0

    @asynccontextmanager
    async def user_session(self, user_id: int) -> AsyncIterator[dict[str, float]]:
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        wait_started = time.perf_counter()

        if lock.locked():
            self._wait_events += 1

        await lock.acquire()
        wait_ms = round((time.perf_counter() - wait_started) * 1000, 1)
        self._last_wait_ms = wait_ms
        self._max_wait_ms = max(self._max_wait_ms, wait_ms)
        self._active_sessions += 1

        try:
            yield {
                "wait_ms": wait_ms,
            }
        finally:
            self._active_sessions = max(0, self._active_sessions - 1)
            lock.release()

    def get_runtime_stats(self) -> dict[str, int | float]:
        return {
            "tracked_users": len(self._locks),
            "active_sessions": self._active_sessions,
            "wait_events": self._wait_events,
            "last_wait_ms": self._last_wait_ms,
            "max_wait_ms": self._max_wait_ms,
        }
