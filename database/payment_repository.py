import json
from typing import Any


class PaymentRepository:
    def __init__(self, db):
        self.db = db

    async def save_payment(
        self,
        user_id: int,
        provider: str,
        external_payment_id: str,
        amount: float,
        currency: str,
        status: str,
        paid_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        is_first_payment = 0
        effective_paid_at = paid_at
        if status == "paid":
            cursor = await self.db.connection.execute(
                """
                SELECT 1
                FROM payments
                WHERE user_id = ? AND status = 'paid'
                LIMIT 1
                """,
                (user_id,),
            )
            existing_paid = await cursor.fetchone()
            is_first_payment = 0 if existing_paid else 1
            if effective_paid_at is None:
                paid_at_cursor = await self.db.connection.execute(
                    "SELECT CURRENT_TIMESTAMP"
                )
                paid_at_row = await paid_at_cursor.fetchone()
                effective_paid_at = paid_at_row[0] if paid_at_row else None

        await self.db.connection.execute(
            """
            INSERT INTO payments (
                user_id,
                provider,
                external_payment_id,
                amount,
                currency,
                status,
                is_first_payment,
                paid_at,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, external_payment_id)
            DO UPDATE SET
                amount = excluded.amount,
                currency = excluded.currency,
                status = excluded.status,
                is_first_payment = CASE
                    WHEN excluded.status = 'paid' AND payments.status != 'paid'
                    THEN excluded.is_first_payment
                    ELSE payments.is_first_payment
                END,
                paid_at = excluded.paid_at,
                metadata_json = excluded.metadata_json
            """,
            (
                user_id,
                provider,
                external_payment_id,
                amount,
                currency,
                status,
                is_first_payment,
                effective_paid_at,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        await self.db.connection.commit()
        return {
            "is_first_payment": bool(is_first_payment),
            "paid_at": effective_paid_at,
        }

    async def get_overview(self) -> dict[str, Any]:
        total_paid_cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM payments
            WHERE status = 'paid'
            """
        )
        total_paid_row = await total_paid_cursor.fetchone()

        first_paid_cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM payments
            WHERE status = 'paid' AND is_first_payment = 1
            """
        )
        first_paid_row = await first_paid_cursor.fetchone()

        paid_users_cursor = await self.db.connection.execute(
            """
            SELECT COUNT(DISTINCT user_id)
            FROM payments
            WHERE status = 'paid'
            """
        )
        paid_users_row = await paid_users_cursor.fetchone()

        return {
            "successful_payments": total_paid_row[0] if total_paid_row else 0,
            "revenue": float(total_paid_row[1] if total_paid_row else 0),
            "first_payments": first_paid_row[0] if first_paid_row else 0,
            "paid_users": paid_users_row[0] if paid_users_row else 0,
        }

    async def get_successful_payments_since(self, days: int) -> int:
        cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM payments
            WHERE status = 'paid'
              AND paid_at IS NOT NULL
              AND paid_at >= datetime('now', ?)
            """,
            (f"-{days} days",),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_first_payments_since(self, days: int) -> int:
        cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM payments
            WHERE status = 'paid'
              AND is_first_payment = 1
              AND paid_at IS NOT NULL
              AND paid_at >= datetime('now', ?)
            """,
            (f"-{days} days",),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_daily_payments(self, days: int = 14) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                DATE(COALESCE(paid_at, created_at)) AS day,
                COUNT(*) AS successful_payments,
                COALESCE(SUM(amount), 0) AS revenue,
                COALESCE(SUM(CASE WHEN is_first_payment = 1 THEN 1 ELSE 0 END), 0) AS first_payments
            FROM payments
            WHERE status = 'paid'
              AND DATE(COALESCE(paid_at, created_at)) >= DATE('now', ?)
            GROUP BY DATE(COALESCE(paid_at, created_at))
            ORDER BY day ASC
            """,
            (f"-{days - 1} days",),
        )
        rows = await cursor.fetchall()
        return [
            {
                "day": row[0],
                "successful_payments": row[1],
                "revenue": float(row[2]),
                "first_payments": row[3],
            }
            for row in rows
        ]

    async def get_recent_payments(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                user_id,
                provider,
                external_payment_id,
                amount,
                currency,
                status,
                is_first_payment,
                COALESCE(paid_at, created_at) AS event_time
            FROM payments
            ORDER BY event_time DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "provider": row[1],
                "external_payment_id": row[2],
                "amount": float(row[3]),
                "currency": row[4],
                "status": row[5],
                "is_first_payment": bool(row[6]),
                "event_time": row[7],
            }
            for row in rows
        ]
