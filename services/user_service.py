from typing import Any


class UserService:
    def __init__(self, db):
        self.db = db

    async def init_table(self) -> None:
        await self.db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                active_mode TEXT DEFAULT 'base',
                is_premium INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.db.connection.commit()

    async def register_user(self, telegram_user) -> None:
        await self.db.connection.execute(
            """
            INSERT OR IGNORE INTO users
            (id, username, first_name, active_mode, is_premium)
            VALUES (?, ?, ?, 'base', 0)
            """,
            (
                telegram_user.id,
                telegram_user.username,
                telegram_user.first_name,
            ),
        )
        await self.db.connection.commit()

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            """
            SELECT id, username, first_name, active_mode, is_premium, created_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "username": row[1],
            "first_name": row[2],
            "active_mode": row[3],
            "is_premium": bool(row[4]),
            "created_at": row[5],
        }

    async def get_total_users(self) -> int:
        cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM users
            """
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_premium_users_count(self) -> int:
        cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE is_premium = 1
            """
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_all_user_ids(self) -> list[int]:
        cursor = await self.db.connection.execute(
            """
            SELECT id
            FROM users
            ORDER BY id
            """
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_new_users_since(self, days: int) -> int:
        cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE created_at >= datetime('now', ?)
            """,
            (f"-{days} days",),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_daily_registrations(self, days: int = 14) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS users_count
            FROM users
            WHERE DATE(created_at) >= DATE('now', ?)
            GROUP BY DATE(created_at)
            ORDER BY day ASC
            """,
            (f"-{days - 1} days",),
        )
        rows = await cursor.fetchall()
        return [{"day": row[0], "users_count": row[1]} for row in rows]

    async def get_recent_users(self, limit: int = 20) -> list[dict[str, Any]]:
        cursor = await self.db.connection.execute(
            """
            SELECT id, username, first_name, active_mode, is_premium, created_at
            FROM users
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "username": row[1],
                "first_name": row[2],
                "active_mode": row[3],
                "is_premium": bool(row[4]),
                "created_at": row[5],
            }
            for row in rows
        ]

    async def user_exists(self, user_id: int) -> bool:
        cursor = await self.db.connection.execute(
            "SELECT 1 FROM users WHERE id = ?",
            (user_id,),
        )
        return await cursor.fetchone() is not None

    async def set_mode(self, user_id: int, mode: str) -> bool:
        cursor = await self.db.connection.execute(
            """
            UPDATE users
            SET active_mode = ?
            WHERE id = ?
            """,
            (mode, user_id),
        )
        await self.db.connection.commit()
        return cursor.rowcount > 0

    async def get_active_mode(self, user_id: int) -> str:
        cursor = await self.db.connection.execute(
            """
            SELECT active_mode
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else "base"

    async def set_premium(self, user_id: int, value: bool) -> bool:
        cursor = await self.db.connection.execute(
            """
            UPDATE users
            SET is_premium = ?
            WHERE id = ?
            """,
            (1 if value else 0, user_id),
        )
        await self.db.connection.commit()
        return cursor.rowcount > 0

    async def is_premium(self, user_id: int) -> bool:
        cursor = await self.db.connection.execute(
            """
            SELECT is_premium
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return bool(row[0]) if row else False
