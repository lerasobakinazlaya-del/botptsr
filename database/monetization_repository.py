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

        stages = {
            stage: {"events": 0, "users": 0}
            for stage in self.FUNNEL_STAGES
        }
        for row in rows:
            event_name = str(row[0] or "")
            if event_name not in stages:
                continue
            stages[event_name] = {
                "events": int(row[1] or 0),
                "users": int(row[2] or 0),
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
