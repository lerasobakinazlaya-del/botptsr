from datetime import datetime, timedelta, timezone
from typing import Any


def _parse_db_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_db_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class UserService:
    VALID_SUBSCRIPTION_PLANS = {"free", "pro", "premium"}

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
                subscription_plan TEXT DEFAULT 'free',
                is_premium INTEGER DEFAULT 0,
                premium_expires_at TIMESTAMP NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._ensure_column("subscription_plan", "TEXT DEFAULT 'free'")
        await self._ensure_column("premium_expires_at", "TIMESTAMP NULL")
        await self._ensure_column("is_admin", "INTEGER DEFAULT 0")
        await self.db.connection.execute(
            """
            INSERT OR IGNORE INTO users (
                id,
                username,
                first_name,
                active_mode,
                subscription_plan,
                is_premium,
                premium_expires_at,
                is_admin,
                created_at
            )
            SELECT
                m.user_id,
                NULL,
                '',
                'base',
                'free',
                0,
                NULL,
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
            (id, username, first_name, active_mode, subscription_plan, is_premium, premium_expires_at, is_admin)
            VALUES (?, ?, ?, 'base', 'free', 0, NULL, ?)
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
            SELECT id, username, first_name, active_mode, is_premium, premium_expires_at, is_admin, created_at
            , subscription_plan
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
              AND (premium_expires_at IS NULL OR premium_expires_at > CURRENT_TIMESTAMP)
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
            SELECT id, username, first_name, active_mode, is_premium, premium_expires_at, is_admin, created_at
            , subscription_plan
            FROM users
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def search_users(
        self,
        query: str = "",
        limit: int = 50,
        sort_by: str = "created_desc",
        filter_by: str = "all",
    ) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip()
        safe_limit = max(1, min(limit, 200))
        order_clause = self._build_user_search_order_clause(sort_by)
        where_filter_clause = self._build_user_search_filter_clause(filter_by)

        if normalized_query:
            like_query = f"%{normalized_query}%"
            cursor = await self.db.connection.execute(
                f"""
                SELECT id, username, first_name, active_mode, is_premium, premium_expires_at, is_admin, created_at
                , subscription_plan
                FROM users
                WHERE (
                    CAST(id AS TEXT) LIKE ?
                    OR COALESCE(username, '') LIKE ?
                    OR COALESCE(first_name, '') LIKE ?
                )
                  AND {where_filter_clause}
                ORDER BY
                    CASE
                        WHEN CAST(id AS TEXT) = ? THEN 0
                        WHEN LOWER(COALESCE(username, '')) = LOWER(?) THEN 1
                        WHEN LOWER(COALESCE(first_name, '')) = LOWER(?) THEN 2
                        ELSE 3
                    END,
                    {order_clause}
                LIMIT ?
                """,
                (
                    like_query,
                    like_query,
                    like_query,
                    normalized_query,
                    normalized_query,
                    normalized_query,
                    safe_limit,
                ),
            )
        else:
            cursor = await self.db.connection.execute(
                f"""
                SELECT id, username, first_name, active_mode, is_premium, premium_expires_at, is_admin, created_at
                , subscription_plan
                FROM users
                WHERE {where_filter_clause}
                ORDER BY {order_clause}
                LIMIT ?
                """,
                (safe_limit,),
            )

        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def count_users(self, query: str = "", filter_by: str = "all") -> int:
        normalized_query = str(query or "").strip()
        where_filter_clause = self._build_user_search_filter_clause(filter_by)

        if normalized_query:
            like_query = f"%{normalized_query}%"
            cursor = await self.db.connection.execute(
                f"""
                SELECT COUNT(*)
                FROM users
                WHERE (
                    CAST(id AS TEXT) LIKE ?
                    OR COALESCE(username, '') LIKE ?
                    OR COALESCE(first_name, '') LIKE ?
                )
                  AND {where_filter_clause}
                """,
                (like_query, like_query, like_query),
            )
        else:
            cursor = await self.db.connection.execute(
                f"""
                SELECT COUNT(*)
                FROM users
                WHERE {where_filter_clause}
                """
            )

        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_subscription_segments_overview(self) -> dict[str, int]:
        queries = {
            "all": "SELECT COUNT(*) FROM users",
            "paid_active": (
                "SELECT COUNT(*) FROM users "
                "WHERE subscription_plan IN ('pro', 'premium') "
                "AND (premium_expires_at IS NULL OR premium_expires_at > CURRENT_TIMESTAMP)"
            ),
            "pro_active": (
                "SELECT COUNT(*) FROM users "
                "WHERE subscription_plan = 'pro' "
                "AND (premium_expires_at IS NULL OR premium_expires_at > CURRENT_TIMESTAMP)"
            ),
            "premium_active": (
                "SELECT COUNT(*) FROM users "
                "WHERE subscription_plan = 'premium' "
                "AND (premium_expires_at IS NULL OR premium_expires_at > CURRENT_TIMESTAMP)"
            ),
            "paid_expiring_3d": (
                "SELECT COUNT(*) FROM users "
                "WHERE subscription_plan IN ('pro', 'premium') "
                "AND premium_expires_at IS NOT NULL "
                "AND premium_expires_at > CURRENT_TIMESTAMP "
                "AND premium_expires_at <= datetime('now', '+3 days')"
            ),
            "paid_expired": (
                "SELECT COUNT(*) FROM users "
                "WHERE subscription_plan IN ('pro', 'premium') "
                "AND premium_expires_at IS NOT NULL "
                "AND premium_expires_at <= CURRENT_TIMESTAMP"
            ),
            "free": (
                "SELECT COUNT(*) FROM users "
                "WHERE subscription_plan = 'free' OR premium_expires_at IS NULL "
                "OR premium_expires_at <= CURRENT_TIMESTAMP"
            ),
        }
        result: dict[str, int] = {}
        for key, query in queries.items():
            cursor = await self.db.connection.execute(query)
            row = await cursor.fetchone()
            result[key] = row[0] if row else 0
        return result

    def _build_user_search_order_clause(self, sort_by: str) -> str:
        normalized = str(sort_by or "").strip().lower() or "created_desc"
        clauses = {
            "created_desc": "created_at DESC, id DESC",
            "premium_expiry_asc": (
                "CASE "
                "WHEN subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL AND premium_expires_at > CURRENT_TIMESTAMP THEN 0 "
                "WHEN subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL THEN 1 "
                "ELSE 2 END, "
                "premium_expires_at ASC, id DESC"
            ),
            "premium_expiry_desc": (
                "CASE "
                "WHEN subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL AND premium_expires_at > CURRENT_TIMESTAMP THEN 0 "
                "WHEN subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL THEN 1 "
                "ELSE 2 END, "
                "premium_expires_at DESC, id DESC"
            ),
            "premium_active_first": (
                "CASE WHEN subscription_plan IN ('pro', 'premium') AND (premium_expires_at IS NULL OR premium_expires_at > CURRENT_TIMESTAMP) "
                "THEN 0 ELSE 1 END, "
                "premium_expires_at ASC, created_at DESC, id DESC"
            ),
            "premium_expiring_soon": (
                "CASE WHEN subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL "
                "AND premium_expires_at > CURRENT_TIMESTAMP THEN 0 ELSE 1 END, "
                "CASE WHEN subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL "
                "AND premium_expires_at > CURRENT_TIMESTAMP THEN premium_expires_at ELSE '9999-12-31 23:59:59' END ASC, "
                "id DESC"
            ),
            "premium_expired": (
                "CASE WHEN subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL "
                "AND premium_expires_at <= CURRENT_TIMESTAMP THEN 0 ELSE 1 END, "
                "premium_expires_at DESC, id DESC"
            ),
        }
        return clauses.get(normalized, clauses["created_desc"])

    def _build_user_search_filter_clause(self, filter_by: str) -> str:
        normalized = str(filter_by or "").strip().lower() or "all"
        clauses = {
            "all": "1 = 1",
            "premium_active": (
                "subscription_plan IN ('pro', 'premium') AND "
                "(premium_expires_at IS NULL OR premium_expires_at > CURRENT_TIMESTAMP)"
            ),
            "premium_expiring_3d": (
                "subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL "
                "AND premium_expires_at > CURRENT_TIMESTAMP "
                "AND premium_expires_at <= datetime('now', '+3 days')"
            ),
            "premium_expired": (
                "subscription_plan IN ('pro', 'premium') AND premium_expires_at IS NOT NULL "
                "AND premium_expires_at <= CURRENT_TIMESTAMP"
            ),
            "without_premium": (
                "subscription_plan = 'free' OR premium_expires_at IS NULL "
                "OR premium_expires_at <= CURRENT_TIMESTAMP"
            ),
        }
        return clauses.get(normalized, clauses["all"])

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
            SET subscription_plan = ?,
                is_premium = ?,
                premium_expires_at = CASE
                    WHEN ? = 1 THEN premium_expires_at
                    ELSE NULL
                END
            WHERE id = ?
            """,
            ("premium" if value else "free", 1 if value else 0, 1 if value else 0, user_id),
        )
        await self.db.connection.commit()
        return cursor.rowcount > 0

    async def set_subscription_plan_until(self, user_id: int, plan_key: str, expires_at: datetime | None) -> bool:
        normalized_plan = self._normalize_subscription_plan(plan_key, fallback="free")
        active_flag = normalized_plan != "free" and expires_at is not None
        cursor = await self.db.connection.execute(
            """
            UPDATE users
            SET is_premium = ?,
                subscription_plan = ?,
                premium_expires_at = ?
            WHERE id = ?
            """,
            (
                1 if active_flag else 0,
                normalized_plan if active_flag else "free",
                _format_db_timestamp(expires_at) if active_flag and expires_at is not None else None,
                user_id,
            ),
        )
        await self.db.connection.commit()
        return cursor.rowcount > 0

    async def set_premium_until(self, user_id: int, expires_at: datetime | None) -> bool:
        return await self.set_subscription_plan_until(user_id, "premium", expires_at)

    async def grant_premium_days(self, user_id: int, days: int) -> str | None:
        return await self.grant_subscription_days(user_id, "premium", days)

    async def grant_subscription_days(self, user_id: int, plan_key: str, days: int) -> str | None:
        safe_days = max(1, int(days))
        normalized_plan = self._normalize_subscription_plan(plan_key, fallback="premium")
        current_user = await self.get_user(user_id)
        current_expiry = _parse_db_timestamp(
            current_user.get("premium_expires_at") if current_user else None
        )
        start_at = current_expiry if current_expiry and current_expiry > datetime.now(timezone.utc) else datetime.now(timezone.utc)
        new_expiry = start_at + timedelta(days=safe_days)
        await self.set_subscription_plan_until(user_id, normalized_plan, new_expiry)
        return _format_db_timestamp(new_expiry)

    async def is_premium(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user.get("is_premium"))

    async def get_subscription_plan(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        return self._normalize_subscription_plan((user or {}).get("subscription_plan"), fallback="free")

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
        subscription_plan: str | None = None,
        is_admin: bool | None = None,
    ) -> dict[str, Any]:
        existing = await self.get_user(user_id)

        mode_value = active_mode or (existing["active_mode"] if existing else "base")
        existing_plan = self._normalize_subscription_plan((existing or {}).get("subscription_plan"), fallback="free")
        normalized_plan = (
            self._normalize_subscription_plan(subscription_plan, fallback=existing_plan)
            if subscription_plan is not None
            else existing_plan
        )
        if is_premium is not None:
            normalized_plan = "premium" if bool(is_premium) else "free"
        premium_value = normalized_plan != "free"
        admin_value = (
            bool(is_admin)
            if is_admin is not None
            else (existing["is_admin"] if existing else False)
        )
        premium_expires_at = existing.get("premium_expires_at") if existing else None
        if not premium_value:
            premium_expires_at = None
            normalized_plan = "free"

        if self._is_static_admin(user_id):
            admin_value = True

        await self.db.connection.execute(
            """
            INSERT OR IGNORE INTO users
            (id, username, first_name, active_mode, subscription_plan, is_premium, premium_expires_at, is_admin)
            VALUES (?, NULL, '', ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                mode_value,
                normalized_plan,
                1 if premium_value else 0,
                premium_expires_at,
                1 if admin_value else 0,
            ),
        )
        await self.db.connection.execute(
            """
            UPDATE users
            SET active_mode = ?,
                subscription_plan = ?,
                is_premium = ?,
                premium_expires_at = ?,
                is_admin = ?
            WHERE id = ?
            """,
            (
                mode_value,
                normalized_plan,
                1 if premium_value else 0,
                premium_expires_at,
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
                (id, username, first_name, active_mode, subscription_plan, is_premium, premium_expires_at, is_admin)
                VALUES (?, NULL, '', 'base', 'free', 0, NULL, 1)
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
        premium_expires_at = row[5]
        subscription_plan = self._resolve_row_subscription_plan(
            row[8] if len(row) > 8 else None,
            bool(row[4]),
            premium_expires_at,
        )
        return {
            "id": row[0],
            "username": row[1],
            "first_name": row[2],
            "active_mode": row[3],
            "subscription_plan": subscription_plan,
            "is_premium": self._is_paid_plan_active(subscription_plan, premium_expires_at),
            "premium_expires_at": premium_expires_at,
            "is_admin": bool(row[6]) or self._is_static_admin(int(row[0])),
            "created_at": row[7],
        }

    def _resolve_row_subscription_plan(
        self,
        stored_plan: str | None,
        is_premium_flag: bool,
        premium_expires_at: str | None,
    ) -> str:
        normalized_stored = self._normalize_subscription_plan(stored_plan, fallback="")
        if normalized_stored:
            if normalized_stored == "free":
                return "free"
            return normalized_stored if self._is_paid_plan_active(normalized_stored, premium_expires_at) else "free"
        if not is_premium_flag:
            return "free"
        return "premium" if self._is_paid_plan_active("premium", premium_expires_at) else "free"

    def _is_paid_plan_active(self, plan_key: str, premium_expires_at: str | None) -> bool:
        if self._normalize_subscription_plan(plan_key, fallback="free") == "free":
            return False
        expires_at = _parse_db_timestamp(premium_expires_at)
        if expires_at is None:
            return True
        return expires_at > datetime.now(timezone.utc)

    def _normalize_subscription_plan(self, plan_key: Any, *, fallback: str) -> str:
        normalized = str(plan_key or "").strip().lower()
        if normalized in self.VALID_SUBSCRIPTION_PLANS:
            return normalized
        return fallback
