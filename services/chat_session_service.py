import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    released_at: float | None = None


class ChatSessionService:
    def __init__(self, *, lock_ttl_seconds: float = 300.0, clock=time.monotonic) -> None:
        self._locks: dict[int, _LockEntry] = {}
        self._active_sessions = 0
        self._wait_events = 0
        self._last_wait_ms = 0.0
        self._max_wait_ms = 0.0
        self._lock_ttl_seconds = max(0.0, float(lock_ttl_seconds))
        self._clock = clock

    def _get_lock_entry(self, user_id: int) -> _LockEntry:
        now = self._clock()
        self._cleanup_idle_locks(now)
        entry = self._locks.get(user_id)
        if entry is None:
            entry = _LockEntry(lock=asyncio.Lock())
            self._locks[user_id] = entry
        return entry

    def _cleanup_idle_locks(self, now: float | None = None) -> None:
        current_time = self._clock() if now is None else now
        if not self._locks:
            return

        expired_users = [
            user_id
            for user_id, entry in self._locks.items()
            if not entry.lock.locked()
            and entry.released_at is not None
            and (current_time - entry.released_at) >= self._lock_ttl_seconds
        ]
        for user_id in expired_users:
            self._locks.pop(user_id, None)

    @asynccontextmanager
    async def user_session(self, user_id: int) -> AsyncIterator[dict[str, float]]:
        entry = self._get_lock_entry(user_id)
        wait_started = time.perf_counter()

        if entry.lock.locked():
            self._wait_events += 1

        await entry.lock.acquire()
        entry.released_at = None
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
            entry.lock.release()
            entry.released_at = self._clock()
            self._cleanup_idle_locks()

    def get_runtime_stats(self) -> dict[str, int | float]:
        self._cleanup_idle_locks()
        return {
            "tracked_users": len(self._locks),
            "active_sessions": self._active_sessions,
            "wait_events": self._wait_events,
            "last_wait_ms": self._last_wait_ms,
            "max_wait_ms": self._max_wait_ms,
        }
