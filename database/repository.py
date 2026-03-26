import logging
from datetime import datetime, timezone
from typing import Any, List

from services.memory_engine import ChatMessage


logger = logging.getLogger(__name__)


def _sqlite_timestamp_to_unix(value: str | None) -> float:
    if not value:
        return 0.0

    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


class MessageRepository:
    def __init__(self, db):
        self.db = db

    async def _commit(self):
        await self.db.connection.commit()

    async def save(
        self,
        user_id: int,
        role: str,
        text: str,
        *,
        commit: bool = True,
    ) -> None:
        await self.db.connection.execute(
            """
            INSERT INTO messages (user_id, role, text)
            VALUES (?, ?, ?)
            """,
            (user_id, role, text),
        )
        if commit:
            await self._commit()

        logger.debug("[DB] Saved message | user_id=%s | role=%s", user_id, role)

    async def get_last_messages(
        self,
        user_id: int,
        limit: int = 20,
    ) -> List[ChatMessage]:
        cursor = await self.db.connection.execute(
            """
            SELECT role, text, created_at
            FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

        rows = await cursor.fetchall()
        rows.reverse()

        return [
            ChatMessage(
                role=row[0],
                content=row[1],
                timestamp=_sqlite_timestamp_to_unix(row[2]),
            )
            for row in rows
        ]

    async def get_total_messages(self) -> int:
        cursor = await self.db.connection.execute("SELECT COUNT(*) FROM messages")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_total_users(self) -> int:
        cursor = await self.db.connection.execute(
            "SELECT COUNT(DISTINCT user_id) FROM messages"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def clear_user_history(self, user_id: int, *, commit: bool = True) -> None:
        await self.db.connection.execute(
            "DELETE FROM messages WHERE user_id = ?",
            (user_id,),
        )
        if commit:
            await self._commit()
        logger.info("[DB] Cleared history for user %s", user_id)

    async def get_user_messages_count_today(self, user_id: int) -> int:
        cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE user_id = ?
              AND role = 'user'
              AND DATE(created_at) = DATE('now')
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_reengagement_candidates(
        self,
        *,
        idle_hours: int,
        recent_window_days: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                user_id,
                MAX(CASE WHEN role = 'user' THEN created_at END) AS last_user_message_at,
                MAX(CASE WHEN role = 'assistant' THEN created_at END) AS last_assistant_message_at,
                MAX(created_at) AS last_message_at
            FROM messages
            GROUP BY user_id
            HAVING last_user_message_at IS NOT NULL
               AND datetime(last_user_message_at) <= datetime('now', ?)
               AND datetime(last_message_at) >= datetime('now', ?)
            ORDER BY datetime(last_user_message_at) ASC
            LIMIT ?
            """,
            (f"-{max(1, int(idle_hours))} hours", f"-{max(1, int(recent_window_days))} days", max(1, int(limit))),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "last_user_message_at": row[1],
                "last_assistant_message_at": row[2],
                "last_message_at": row[3],
            }
            for row in rows
        ]
