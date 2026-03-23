import json
from typing import Any


class AdminMetricsService:
    CACHE_KEY = "admin:overview:v1"

    def __init__(
        self,
        user_service,
        message_repository,
        payment_repository,
        state_repository,
        ai_service,
        redis=None,
        cache_ttl: int = 15,
    ):
        self.user_service = user_service
        self.message_repository = message_repository
        self.payment_repository = payment_repository
        self.state_repository = state_repository
        self.ai_service = ai_service
        self.redis = redis
        self.cache_ttl = cache_ttl

    async def get_overview(self) -> dict[str, Any]:
        cached_payload = await self._get_cached_payload()
        if cached_payload is None:
            cached_payload = await self._build_cached_payload()
            await self._store_cached_payload(cached_payload)

        return {
            **cached_payload,
            "runtime": self.ai_service.get_runtime_stats(),
        }

    async def invalidate_cache(self) -> None:
        if self.redis is None:
            return
        await self.redis.delete(self.CACHE_KEY)

    async def _get_cached_payload(self) -> dict[str, Any] | None:
        if self.redis is None or self.cache_ttl <= 0:
            return None

        raw_payload = await self.redis.get(self.CACHE_KEY)
        if not raw_payload:
            return None

        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")

        return json.loads(raw_payload)

    async def _store_cached_payload(self, payload: dict[str, Any]) -> None:
        if self.redis is None or self.cache_ttl <= 0:
            return

        await self.redis.set(
            self.CACHE_KEY,
            json.dumps(payload, ensure_ascii=False),
            ex=self.cache_ttl,
        )

    async def _build_cached_payload(self) -> dict[str, Any]:
        payment_overview = await self.payment_repository.get_overview()
        total_users = await self.user_service.get_total_users()
        premium_users = await self.user_service.get_premium_users_count()
        total_messages = await self.message_repository.get_total_messages()
        active_users = await self.message_repository.get_total_users()
        support_stats = await self.state_repository.get_support_stats()

        return {
            "users": {
                "total": total_users,
                "new_1d": await self.user_service.get_new_users_since(1),
                "new_7d": await self.user_service.get_new_users_since(7),
                "new_30d": await self.user_service.get_new_users_since(30),
                "premium_total": premium_users,
                "active_with_messages": active_users,
            },
            "payments": {
                **payment_overview,
                "successful_1d": await self.payment_repository.get_successful_payments_since(1),
                "successful_7d": await self.payment_repository.get_successful_payments_since(7),
                "successful_30d": await self.payment_repository.get_successful_payments_since(30),
                "first_1d": await self.payment_repository.get_first_payments_since(1),
                "first_7d": await self.payment_repository.get_first_payments_since(7),
                "first_30d": await self.payment_repository.get_first_payments_since(30),
            },
            "content": {
                "messages_total": total_messages,
            },
            "support": support_stats,
            "series": {
                "users": await self.user_service.get_daily_registrations(days=14),
                "payments": await self.payment_repository.get_daily_payments(days=14),
            },
            "recent": {
                "users": await self.user_service.get_recent_users(limit=20),
                "payments": await self.payment_repository.get_recent_payments(limit=20),
            },
        }
