class ProactiveRepository:
    def __init__(self, db):
        self.db = db

    async def init_table(self) -> None:
        await self.db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS proactive_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                trigger_kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'sent',
                source_last_user_message_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                error_text TEXT NULL
            )
            """
        )
        await self.db.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_proactive_messages_user_created
            ON proactive_messages (user_id, created_at DESC)
            """
        )
        await self.db.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_proactive_messages_user_source
            ON proactive_messages (user_id, source_last_user_message_at)
            """
        )
        await self.db.connection.commit()

    async def has_event_for_silence(
        self,
        *,
        user_id: int,
        source_last_user_message_at: str | None,
    ) -> bool:
        if not source_last_user_message_at:
            return False

        cursor = await self.db.connection.execute(
            """
            SELECT 1
            FROM proactive_messages
            WHERE user_id = ?
              AND source_last_user_message_at = ?
            LIMIT 1
            """,
            (int(user_id), source_last_user_message_at),
        )
        return await cursor.fetchone() is not None

    async def has_recent_event(
        self,
        *,
        user_id: int,
        cooldown_hours: int,
    ) -> bool:
        safe_cooldown_hours = max(1, int(cooldown_hours))
        cursor = await self.db.connection.execute(
            """
            SELECT 1
            FROM proactive_messages
            WHERE user_id = ?
              AND created_at >= datetime('now', ?)
            LIMIT 1
            """,
            (int(user_id), f"-{safe_cooldown_hours} hours"),
        )
        return await cursor.fetchone() is not None

    async def log_event(
        self,
        *,
        user_id: int,
        trigger_kind: str,
        status: str,
        source_last_user_message_at: str | None,
        error_text: str | None = None,
    ) -> None:
        await self.db.connection.execute(
            """
            INSERT INTO proactive_messages (
                user_id,
                trigger_kind,
                status,
                source_last_user_message_at,
                error_text
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                str(trigger_kind).strip() or "inactivity_followup",
                str(status).strip() or "sent",
                source_last_user_message_at,
                (str(error_text).strip()[:500] if error_text else None),
            ),
        )
        await self.db.connection.commit()

    async def get_overview(self) -> dict:
        cursor = await self.db.connection.execute(
            """
            SELECT
                COUNT(*) AS total_events,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent_total,
                SUM(CASE WHEN status != 'sent' THEN 1 ELSE 0 END) AS failed_total,
                SUM(CASE WHEN created_at >= datetime('now', '-1 day') THEN 1 ELSE 0 END) AS total_1d,
                SUM(CASE WHEN status = 'sent' AND created_at >= datetime('now', '-1 day') THEN 1 ELSE 0 END) AS sent_1d,
                SUM(CASE WHEN status != 'sent' AND created_at >= datetime('now', '-1 day') THEN 1 ELSE 0 END) AS failed_1d,
                COUNT(DISTINCT CASE WHEN status = 'sent' THEN user_id END) AS users_contacted_total,
                COUNT(DISTINCT CASE WHEN status = 'sent' AND created_at >= datetime('now', '-7 day') THEN user_id END) AS users_contacted_7d
            FROM proactive_messages
            """
        )
        row = await cursor.fetchone()
        if row is None:
            return {
                "total_events": 0,
                "sent_total": 0,
                "failed_total": 0,
                "total_1d": 0,
                "sent_1d": 0,
                "failed_1d": 0,
                "users_contacted_total": 0,
                "users_contacted_7d": 0,
                "recent": [],
            }

        recent = await self.get_recent_events(limit=20)
        return {
            "total_events": int(row[0] or 0),
            "sent_total": int(row[1] or 0),
            "failed_total": int(row[2] or 0),
            "total_1d": int(row[3] or 0),
            "sent_1d": int(row[4] or 0),
            "failed_1d": int(row[5] or 0),
            "users_contacted_total": int(row[6] or 0),
            "users_contacted_7d": int(row[7] or 0),
            "recent": recent,
        }

    async def get_recent_events(self, *, limit: int = 20) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        cursor = await self.db.connection.execute(
            """
            SELECT user_id, trigger_kind, status, source_last_user_message_at, created_at, error_text
            FROM proactive_messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": int(row[0]),
                "trigger_kind": row[1],
                "status": row[2],
                "source_last_user_message_at": row[3],
                "created_at": row[4],
                "error_text": row[5],
            }
            for row in rows
        ]
