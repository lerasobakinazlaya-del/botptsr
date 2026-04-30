import json
from typing import Any


class OpenAIUsageRepository:
    def __init__(self, db):
        self.db = db
        self._users_table_exists_cache: bool | None = None

    async def log_event(
        self,
        *,
        user_id: int | None,
        source: str,
        model: str,
        total_tokens: int | None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        cached_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
        latency_ms: float | None = None,
        finish_reason: str | None = None,
        request_user: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.db.connection.execute(
            """
            INSERT INTO openai_usage_events (
                user_id,
                source,
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                reasoning_tokens,
                cached_tokens,
                estimated_cost_usd,
                latency_ms,
                finish_reason,
                request_user,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id) if user_id not in (None, "") else None,
                str(source).strip() or "unknown",
                str(model).strip() or "",
                self._normalize_int(prompt_tokens),
                self._normalize_int(completion_tokens),
                self._normalize_int(total_tokens),
                self._normalize_int(reasoning_tokens),
                self._normalize_int(cached_tokens),
                self._normalize_float(estimated_cost_usd),
                self._normalize_float(latency_ms),
                str(finish_reason).strip() if finish_reason else None,
                str(request_user).strip() if request_user else None,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        await self.db.connection.commit()

    async def get_overview(self) -> dict[str, Any]:
        totals = await self._fetch_scalar_overview()
        return {
            **totals,
            "by_source_1d": await self.get_breakdown_by_source(days=1),
            "by_source_7d": await self.get_breakdown_by_source(days=7),
            "by_source_30d": await self.get_breakdown_by_source(days=30),
            "by_model_30d": await self.get_breakdown_by_model(days=30),
            "top_users_1d": await self.get_top_users(days=1),
            "top_users_7d": await self.get_top_users(days=7),
            "top_users_30d": await self.get_top_users(days=30),
            "daily_14d": await self.get_daily_usage(days=14),
            "recent": await self.get_recent_events(limit=20),
        }

    async def get_breakdown_by_source(self, *, days: int) -> dict[str, Any]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                COALESCE(NULLIF(source, ''), 'unknown') AS source,
                COUNT(*) AS requests,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM openai_usage_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY COALESCE(NULLIF(source, ''), 'unknown')
            ORDER BY total_tokens DESC, requests DESC, source ASC
            """,
            (f"-{max(1, int(days))} days",),
        )
        rows = await cursor.fetchall()
        return {
            str(row[0] or "unknown"): {
                "requests": int(row[1] or 0),
                "total_tokens": int(row[2] or 0),
                "estimated_cost_usd": round(float(row[3] or 0.0), 6),
                "avg_latency_ms": round(float(row[4] or 0.0), 1),
            }
            for row in rows
        }

    async def get_breakdown_by_model(self, *, days: int) -> dict[str, Any]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                COALESCE(NULLIF(model, ''), 'unknown') AS model,
                COUNT(*) AS requests,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
            FROM openai_usage_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY COALESCE(NULLIF(model, ''), 'unknown')
            ORDER BY total_tokens DESC, requests DESC, model ASC
            """,
            (f"-{max(1, int(days))} days",),
        )
        rows = await cursor.fetchall()
        return {
            str(row[0] or "unknown"): {
                "requests": int(row[1] or 0),
                "total_tokens": int(row[2] or 0),
                "estimated_cost_usd": round(float(row[3] or 0.0), 6),
            }
            for row in rows
        }

    async def get_top_users(self, *, days: int, limit: int = 20) -> list[dict[str, Any]]:
        if await self._users_table_exists():
            cursor = await self.db.connection.execute(
                """
                SELECT
                    e.user_id,
                    COALESCE(NULLIF(u.username, ''), NULL) AS username,
                    COALESCE(NULLIF(u.first_name, ''), NULL) AS first_name,
                    COUNT(*) AS requests,
                    COALESCE(SUM(e.prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(e.completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(e.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(e.estimated_cost_usd), 0) AS estimated_cost_usd,
                    MAX(e.created_at) AS last_seen_at
                FROM openai_usage_events e
                LEFT JOIN users u ON u.id = e.user_id
                WHERE e.created_at >= datetime('now', ?)
                GROUP BY e.user_id, COALESCE(NULLIF(u.username, ''), NULL), COALESCE(NULLIF(u.first_name, ''), NULL)
                ORDER BY total_tokens DESC, requests DESC, e.user_id ASC
                LIMIT ?
                """,
                (
                    f"-{max(1, int(days))} days",
                    max(1, min(int(limit), 100)),
                ),
            )
        else:
            cursor = await self.db.connection.execute(
                """
                SELECT
                    e.user_id,
                    NULL AS username,
                    NULL AS first_name,
                    COUNT(*) AS requests,
                    COALESCE(SUM(e.prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(e.completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(e.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(e.estimated_cost_usd), 0) AS estimated_cost_usd,
                    MAX(e.created_at) AS last_seen_at
                FROM openai_usage_events e
                WHERE e.created_at >= datetime('now', ?)
                GROUP BY e.user_id
                ORDER BY total_tokens DESC, requests DESC, e.user_id ASC
                LIMIT ?
                """,
                (
                    f"-{max(1, int(days))} days",
                    max(1, min(int(limit), 100)),
                ),
            )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "username": row[1],
                "first_name": row[2],
                "requests": int(row[3] or 0),
                "prompt_tokens": int(row[4] or 0),
                "completion_tokens": int(row[5] or 0),
                "total_tokens": int(row[6] or 0),
                "estimated_cost_usd": round(float(row[7] or 0.0), 6),
                "last_seen_at": row[8],
            }
            for row in rows
        ]

    async def get_daily_usage(self, *, days: int) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                DATE(created_at) AS day,
                COUNT(*) AS requests,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
            FROM openai_usage_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY DATE(created_at)
            ORDER BY day ASC
            """,
            (f"-{max(1, int(days))} days",),
        )
        rows = await cursor.fetchall()
        return [
            {
                "day": str(row[0] or ""),
                "requests": int(row[1] or 0),
                "total_tokens": int(row[2] or 0),
                "estimated_cost_usd": round(float(row[3] or 0.0), 6),
            }
            for row in rows
        ]

    async def get_recent_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if await self._users_table_exists():
            cursor = await self.db.connection.execute(
                """
                SELECT
                    e.user_id,
                    COALESCE(NULLIF(u.username, ''), NULL) AS username,
                    COALESCE(NULLIF(u.first_name, ''), NULL) AS first_name,
                    e.source,
                    e.model,
                    e.prompt_tokens,
                    e.completion_tokens,
                    e.total_tokens,
                    e.reasoning_tokens,
                    e.cached_tokens,
                    e.estimated_cost_usd,
                    e.latency_ms,
                    e.finish_reason,
                    e.request_user,
                    e.metadata_json,
                    e.created_at
                FROM openai_usage_events e
                LEFT JOIN users u ON u.id = e.user_id
                ORDER BY e.id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            )
        else:
            cursor = await self.db.connection.execute(
                """
                SELECT
                    e.user_id,
                    NULL AS username,
                    NULL AS first_name,
                    e.source,
                    e.model,
                    e.prompt_tokens,
                    e.completion_tokens,
                    e.total_tokens,
                    e.reasoning_tokens,
                    e.cached_tokens,
                    e.estimated_cost_usd,
                    e.latency_ms,
                    e.finish_reason,
                    e.request_user,
                    e.metadata_json,
                    e.created_at
                FROM openai_usage_events e
                ORDER BY e.id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "username": row[1],
                "first_name": row[2],
                "source": row[3],
                "model": row[4],
                "prompt_tokens": int(row[5] or 0) if row[5] is not None else None,
                "completion_tokens": int(row[6] or 0) if row[6] is not None else None,
                "total_tokens": int(row[7] or 0) if row[7] is not None else None,
                "reasoning_tokens": int(row[8] or 0) if row[8] is not None else None,
                "cached_tokens": int(row[9] or 0) if row[9] is not None else None,
                "estimated_cost_usd": round(float(row[10] or 0.0), 6) if row[10] is not None else None,
                "latency_ms": round(float(row[11] or 0.0), 1) if row[11] is not None else None,
                "finish_reason": row[12],
                "request_user": row[13],
                "metadata": self._load_metadata(row[14]),
                "created_at": row[15],
            }
            for row in rows
        ]

    async def _fetch_scalar_overview(self) -> dict[str, Any]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                COUNT(*) AS requests_total,
                COALESCE(SUM(total_tokens), 0) AS tokens_total,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens_total,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens_total,
                COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END) AS users_total,
                COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd_total,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                COALESCE(MAX(latency_ms), 0) AS max_latency_ms,
                SUM(CASE WHEN created_at >= datetime('now', '-1 day') THEN 1 ELSE 0 END) AS requests_1d,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-1 day') THEN total_tokens ELSE 0 END), 0) AS tokens_1d,
                COUNT(DISTINCT CASE WHEN created_at >= datetime('now', '-1 day') AND user_id IS NOT NULL THEN user_id END) AS users_1d,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-1 day') THEN estimated_cost_usd ELSE 0 END), 0) AS estimated_cost_usd_1d,
                SUM(CASE WHEN created_at >= datetime('now', '-7 day') THEN 1 ELSE 0 END) AS requests_7d,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-7 day') THEN total_tokens ELSE 0 END), 0) AS tokens_7d,
                COUNT(DISTINCT CASE WHEN created_at >= datetime('now', '-7 day') AND user_id IS NOT NULL THEN user_id END) AS users_7d,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-7 day') THEN estimated_cost_usd ELSE 0 END), 0) AS estimated_cost_usd_7d,
                SUM(CASE WHEN created_at >= datetime('now', '-30 day') THEN 1 ELSE 0 END) AS requests_30d,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-30 day') THEN total_tokens ELSE 0 END), 0) AS tokens_30d,
                COUNT(DISTINCT CASE WHEN created_at >= datetime('now', '-30 day') AND user_id IS NOT NULL THEN user_id END) AS users_30d,
                COALESCE(SUM(CASE WHEN created_at >= datetime('now', '-30 day') THEN estimated_cost_usd ELSE 0 END), 0) AS estimated_cost_usd_30d
            FROM openai_usage_events
            """
        )
        row = await cursor.fetchone()
        if row is None:
            return {
                "requests_total": 0,
                "tokens_total": 0,
                "prompt_tokens_total": 0,
                "completion_tokens_total": 0,
                "users_total": 0,
                "estimated_cost_usd_total": 0.0,
                "avg_latency_ms": 0.0,
                "max_latency_ms": 0.0,
                "requests_1d": 0,
                "tokens_1d": 0,
                "users_1d": 0,
                "estimated_cost_usd_1d": 0.0,
                "requests_7d": 0,
                "tokens_7d": 0,
                "users_7d": 0,
                "estimated_cost_usd_7d": 0.0,
                "requests_30d": 0,
                "tokens_30d": 0,
                "users_30d": 0,
                "estimated_cost_usd_30d": 0.0,
            }

        return {
            "requests_total": int(row[0] or 0),
            "tokens_total": int(row[1] or 0),
            "prompt_tokens_total": int(row[2] or 0),
            "completion_tokens_total": int(row[3] or 0),
            "users_total": int(row[4] or 0),
            "estimated_cost_usd_total": round(float(row[5] or 0.0), 6),
            "avg_latency_ms": round(float(row[6] or 0.0), 1),
            "max_latency_ms": round(float(row[7] or 0.0), 1),
            "requests_1d": int(row[8] or 0),
            "tokens_1d": int(row[9] or 0),
            "users_1d": int(row[10] or 0),
            "estimated_cost_usd_1d": round(float(row[11] or 0.0), 6),
            "requests_7d": int(row[12] or 0),
            "tokens_7d": int(row[13] or 0),
            "users_7d": int(row[14] or 0),
            "estimated_cost_usd_7d": round(float(row[15] or 0.0), 6),
            "requests_30d": int(row[16] or 0),
            "tokens_30d": int(row[17] or 0),
            "users_30d": int(row[18] or 0),
            "estimated_cost_usd_30d": round(float(row[19] or 0.0), 6),
        }

    @staticmethod
    def _normalize_int(value: int | None) -> int | None:
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _normalize_float(value: float | None) -> float | None:
        if value in (None, ""):
            return None
        return float(value)

    @staticmethod
    def _load_metadata(raw_value: Any) -> dict[str, Any]:
        if raw_value in (None, ""):
            return {}
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    async def _users_table_exists(self) -> bool:
        if self._users_table_exists_cache is not None:
            return self._users_table_exists_cache
        cursor = await self.db.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        )
        self._users_table_exists_cache = await cursor.fetchone() is not None
        return self._users_table_exists_cache
