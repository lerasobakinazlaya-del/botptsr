from typing import Any


class UserPreferenceRepository:
    DEFAULT_PREFERENCES = {
        "proactive_enabled": True,
        "timezone": None,
        "updated_at": None,
    }

    def __init__(self, db):
        self.db = db

    async def init_table(self) -> None:
        await self.db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                proactive_enabled INTEGER NOT NULL DEFAULT 1,
                timezone TEXT NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preference_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_kind TEXT NOT NULL,
                proactive_enabled INTEGER NULL,
                timezone TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.db.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_preference_events_user_kind_created
            ON user_preference_events (user_id, event_kind, created_at DESC)
            """
        )
        await self.db.connection.commit()

    async def get_preferences(
        self,
        user_id: int,
        *,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cursor = await self.db.connection.execute(
            """
            SELECT proactive_enabled, timezone, updated_at
            FROM user_preferences
            WHERE user_id = ?
            """,
            (int(user_id),),
        )
        row = await cursor.fetchone()
        if row is not None:
            return {
                "proactive_enabled": bool(row[0]),
                "timezone": row[1],
                "updated_at": row[2],
            }

        merged = dict(self.DEFAULT_PREFERENCES)
        if isinstance(fallback, dict):
            merged["proactive_enabled"] = bool(
                fallback.get("enabled", merged["proactive_enabled"])
            )
            merged["timezone"] = fallback.get("timezone")
            merged["updated_at"] = fallback.get("updated_at")
        return merged

    async def set_proactive_enabled(self, user_id: int, enabled: bool) -> dict[str, Any]:
        await self.db.connection.execute(
            """
            INSERT INTO user_preferences (user_id, proactive_enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id)
            DO UPDATE SET
                proactive_enabled = excluded.proactive_enabled,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(user_id), 1 if enabled else 0),
        )
        await self._log_event(
            user_id=user_id,
            event_kind="proactive_enabled",
            proactive_enabled=enabled,
            timezone=None,
        )
        await self.db.connection.commit()
        return await self.get_preferences(user_id)

    async def set_timezone(self, user_id: int, timezone_name: str | None) -> dict[str, Any]:
        await self.db.connection.execute(
            """
            INSERT INTO user_preferences (user_id, timezone, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id)
            DO UPDATE SET
                timezone = excluded.timezone,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(user_id), timezone_name),
        )
        await self._log_event(
            user_id=user_id,
            event_kind="timezone",
            proactive_enabled=None,
            timezone=timezone_name,
        )
        await self.db.connection.commit()
        return await self.get_preferences(user_id)

    async def get_stats(self) -> dict[str, int]:
        cursor = await self.db.connection.execute(
            """
            SELECT
                COUNT(*) AS total_users_with_prefs,
                SUM(CASE WHEN proactive_enabled = 0 THEN 1 ELSE 0 END) AS proactive_disabled_users,
                SUM(CASE WHEN timezone IS NOT NULL AND TRIM(timezone) != '' THEN 1 ELSE 0 END) AS users_with_timezone
            FROM user_preferences
            """
        )
        row = await cursor.fetchone()
        return {
            "total_users_with_prefs": int(row[0] or 0),
            "proactive_disabled_users": int(row[1] or 0),
            "users_with_timezone": int(row[2] or 0),
        }

    async def _log_event(
        self,
        *,
        user_id: int,
        event_kind: str,
        proactive_enabled: bool | None,
        timezone: str | None,
    ) -> None:
        await self.db.connection.execute(
            """
            INSERT INTO user_preference_events (
                user_id,
                event_kind,
                proactive_enabled,
                timezone
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(user_id),
                str(event_kind).strip(),
                None if proactive_enabled is None else (1 if proactive_enabled else 0),
                timezone,
            ),
        )
