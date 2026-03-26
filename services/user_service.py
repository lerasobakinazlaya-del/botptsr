from typing import Any


class UserService:
    def __init__(self, db, settings=None):
        self.db = db
        self.settings = settings

    async def init_table(self) -> None:
        await self.db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                active_mode TEXT DEFAULT 'base',
                is_premium INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._ensure_column("is_admin", "INTEGER DEFAULT 0")
        await self.db.connection.execute(
            """
            INSERT OR IGNORE INTO users (
                id,
                username,
                first_name,
                active_mode,
                is_premium,
                is_admin,
                created_at
            )
            SELECT
                m.user_id,
                NULL,
                '',
                'base',
                0,
                0,
                MIN(m.created_at)
            FROM messages m
            LEFT JOIN users u ON u.id = m.user_id
            WHERE u.id IS NULL
            GROUP BY m.user_id
            """
        )
        await self._sync_static_admins()
        await self.db.connection.commit()

    async def register_user(self, telegram_user) -> bool:
        cursor = await self.db.connection.execute(
            """
            INSERT OR IGNORE INTO users
            (id, username, first_name, active_mode, is_premium, is_admin)
            VALUES (?, ?, ?, 'base', 0, ?)
            """,
            (
                telegram_user.id,
                telegram_user.username,
                telegram_user.first_name,
                1 if self._is_static_admin(telegram_user.id) else 0,
            ),
        )
        await self.db.connection.commit()
        return cursor.rowcount > 0

    async def ensure_user(self, telegram_user) -> bool:
        is_new_user = await self.register_user(telegram_user)
        await self.db.connection.execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?,
                is_admin = CASE
                    WHEN ? = 1 THEN 1
                    ELSE is_admin
                END
            WHERE id = ?
            """,
            (
                telegram_user.username,
                telegram_user.first_name,
                1 if self._is_static_admin(telegram_user.id) else 0,
                telegram_user.id,
            ),
        )
        await self.db.connection.commit()
        return is_new_user

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            """
            SELECT id, username, first_name, active_mode, is_premium, is_admin, created_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_user(row)

    async def get_bot_username(self, user_id: int) -> str | None:
        cursor = await self.db.connection.execute(
            """
            SELECT username
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

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

    async def get_admin_users_count(self) -> int:
        cursor = await self.db.connection.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE is_admin = 1
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
            SELECT id, username, first_name, active_mode, is_premium, is_admin, created_at
            FROM users
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def search_users(self, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip()
        safe_limit = max(1, min(limit, 200))

        if normalized_query:
            like_query = f"%{normalized_query}%"
            cursor = await self.db.connection.execute(
                """
                SELECT id, username, first_name, active_mode, is_premium, is_admin, created_at
                FROM users
                WHERE CAST(id AS TEXT) LIKE ?
                   OR COALESCE(username, '') LIKE ?
                   OR COALESCE(first_name, '') LIKE ?
                ORDER BY is_admin DESC, is_premium DESC, created_at DESC, id DESC
                LIMIT ?
                """,
                (like_query, like_query, like_query, safe_limit),
            )
        else:
            cursor = await self.db.connection.execute(
                """
                SELECT id, username, first_name, active_mode, is_premium, is_admin, created_at
                FROM users
                ORDER BY is_admin DESC, is_premium DESC, created_at DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            )

        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

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

    async def set_admin(self, user_id: int, value: bool) -> bool:
        if self._is_static_admin(user_id):
            value = True

        cursor = await self.db.connection.execute(
            """
            UPDATE users
            SET is_admin = ?
            WHERE id = ?
            """,
            (1 if value else 0, user_id),
        )
        await self.db.connection.commit()
        return cursor.rowcount > 0

    async def is_admin(self, user_id: int) -> bool:
        if self._is_static_admin(user_id):
            return True

        cursor = await self.db.connection.execute(
            """
            SELECT is_admin
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return bool(row[0]) if row else False

    async def upsert_user_access(
        self,
        user_id: int,
        *,
        active_mode: str | None = None,
        is_premium: bool | None = None,
        is_admin: bool | None = None,
    ) -> dict[str, Any]:
        existing = await self.get_user(user_id)

        mode_value = active_mode or (existing["active_mode"] if existing else "base")
        premium_value = (
            bool(is_premium)
            if is_premium is not None
            else (existing["is_premium"] if existing else False)
        )
        admin_value = (
            bool(is_admin)
            if is_admin is not None
            else (existing["is_admin"] if existing else False)
        )

        if self._is_static_admin(user_id):
            admin_value = True

        await self.db.connection.execute(
            """
            INSERT OR IGNORE INTO users
            (id, username, first_name, active_mode, is_premium, is_admin)
            VALUES (?, NULL, '', ?, ?, ?)
            """,
            (
                user_id,
                mode_value,
                1 if premium_value else 0,
                1 if admin_value else 0,
            ),
        )
        await self.db.connection.execute(
            """
            UPDATE users
            SET active_mode = ?,
                is_premium = ?,
                is_admin = ?
            WHERE id = ?
            """,
            (
                mode_value,
                1 if premium_value else 0,
                1 if admin_value else 0,
                user_id,
            ),
        )
        await self.db.connection.commit()

        user = await self.get_user(user_id)
        if user is None:
            raise ValueError("User was not saved")
        return user

    async def _ensure_column(self, name: str, definition: str) -> None:
        cursor = await self.db.connection.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        if any(column[1] == name for column in columns):
            return

        await self.db.connection.execute(
            f"ALTER TABLE users ADD COLUMN {name} {definition}"
        )

    async def _sync_static_admins(self) -> None:
        for admin_id in sorted(self._configured_admin_ids()):
            await self.db.connection.execute(
                """
                INSERT OR IGNORE INTO users
                (id, username, first_name, active_mode, is_premium, is_admin)
                VALUES (?, NULL, '', 'base', 0, 1)
                """,
                (admin_id,),
            )
            await self.db.connection.execute(
                """
                UPDATE users
                SET is_admin = 1
                WHERE id = ?
                """,
                (admin_id,),
            )

    def _configured_admin_ids(self) -> set[int]:
        if self.settings is None:
            return set()

        admin_ids = {int(self.settings.owner_id)}
        admin_ids.update(int(user_id) for user_id in self.settings.admin_id)
        return admin_ids

    def _is_static_admin(self, user_id: int) -> bool:
        return user_id in self._configured_admin_ids()

    def _row_to_user(self, row) -> dict[str, Any]:
        return {
            "id": row[0],
            "username": row[1],
            "first_name": row[2],
            "active_mode": row[3],
            "is_premium": bool(row[4]),
            "is_admin": bool(row[5]) or self._is_static_admin(int(row[0])),
            "created_at": row[6],
        }
