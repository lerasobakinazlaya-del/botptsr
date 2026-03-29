import json
from typing import Any


class MonetizationRepository:
    FUNNEL_STAGES = ("offer_shown", "invoice_opened", "paid", "renewed")

    def __init__(self, db):
        self.db = db

    async def log_event(
        self,
        *,
        user_id: int,
        event_name: str,
        offer_trigger: str | None = None,
        offer_variant: str | None = None,
        payment_external_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.db.connection.execute(
            """
            INSERT INTO monetization_events (
                user_id,
                event_name,
                offer_trigger,
                offer_variant,
                payment_external_id,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                event_name,
                offer_trigger,
                offer_variant,
                payment_external_id,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        await self.db.connection.commit()

    async def get_funnel_overview(self, days: int = 30) -> dict[str, Any]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                event_name,
                COUNT(*) AS total_events,
                COUNT(DISTINCT user_id) AS unique_users
            FROM monetization_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY event_name
            """,
            (f"-{days} days",),
        )
        rows = await cursor.fetchall()
        return self._build_funnel_payload(rows, days)

    async def get_segmented_funnel(self, *, days: int = 30, segment_by: str) -> dict[str, Any]:
        if segment_by not in {"offer_trigger", "offer_variant"}:
            raise ValueError("Unsupported segment field")

        cursor = await self.db.connection.execute(
            f"""
            SELECT
                COALESCE(NULLIF({segment_by}, ''), 'unknown') AS segment_value,
                event_name,
                COUNT(*) AS total_events,
                COUNT(DISTINCT user_id) AS unique_users
            FROM monetization_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY COALESCE(NULLIF({segment_by}, ''), 'unknown'), event_name
            ORDER BY segment_value ASC
            """,
            (f"-{days} days",),
        )
        rows = await cursor.fetchall()

        grouped: dict[str, list[tuple[str, int, int]]] = {}
        for row in rows:
            grouped.setdefault(str(row[0] or "unknown"), []).append(
                (str(row[1] or ""), int(row[2] or 0), int(row[3] or 0))
            )

        return {
            "days": days,
            "segment_by": segment_by,
            "segments": {
                segment: self._build_funnel_payload(segment_rows, days)
                for segment, segment_rows in grouped.items()
            },
        }

    async def get_latest_offer_context(self, user_id: int) -> dict[str, str] | None:
        cursor = await self.db.connection.execute(
            """
            SELECT offer_trigger, offer_variant
            FROM monetization_events
            WHERE user_id = ?
              AND event_name IN ('invoice_opened', 'offer_shown')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "offer_trigger": str(row[0] or "").strip(),
            "offer_variant": str(row[1] or "").strip(),
        }

    async def get_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                user_id,
                event_name,
                offer_trigger,
                offer_variant,
                payment_external_id,
                created_at
            FROM monetization_events
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "event_name": row[1],
                "offer_trigger": row[2],
                "offer_variant": row[3],
                "payment_external_id": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round((numerator / denominator) * 100.0, 2)

    def _build_funnel_payload(self, rows, days: int) -> dict[str, Any]:
        stages = {
            stage: {"events": 0, "users": 0}
            for stage in self.FUNNEL_STAGES
        }
        for row in rows:
            event_name = str(row[0] or "")
            if len(row) == 3:
                total_events = int(row[1] or 0)
                unique_users = int(row[2] or 0)
            else:
                total_events = int(row[1] or 0)
                unique_users = int(row[2] or 0)
            if event_name not in stages:
                continue
            stages[event_name] = {
                "events": total_events,
                "users": unique_users,
            }

        offer_users = stages["offer_shown"]["users"]
        invoice_users = stages["invoice_opened"]["users"]
        paid_users = stages["paid"]["users"]
        renewed_users = stages["renewed"]["users"]

        return {
            "days": days,
            "stages": stages,
            "conversion": {
                "offer_to_invoice_pct": self._ratio(invoice_users, offer_users),
                "invoice_to_paid_pct": self._ratio(paid_users, invoice_users),
                "paid_to_renewed_pct": self._ratio(renewed_users, paid_users),
            },
        }
