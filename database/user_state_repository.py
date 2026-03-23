import json
from typing import Any, Dict


class UserStateRepository:
    def __init__(self, db):
        self._db = db

    async def init_table(self) -> None:
        await self._db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_state (
                user_id INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._db.connection.commit()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "active_mode": "base",
            "interaction_count": 0,
            "conversation_phase": "start",
            "emotional_tone": None,
            "user_profile": {
                "goals": [],
                "interests": [],
                "personality_traits": [],
            },
            "memory_flags": {},
            "premium_features_used": 0,
        }

    def _merge_with_default(self, state: Dict[str, Any]) -> Dict[str, Any]:
        default = self._default_state()
        merged = default | state

        user_profile = state.get("user_profile", {})
        if not isinstance(user_profile, dict):
            user_profile = {}

        merged["user_profile"] = default["user_profile"] | user_profile
        return merged

    async def get(self, user_id: int) -> Dict[str, Any]:
        cursor = await self._db.connection.execute(
            "SELECT state_json FROM user_state WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            state = self._default_state()
            await self.save(user_id, state)
            return state

        try:
            state = json.loads(row[0])
        except Exception:
            state = self._default_state()
            await self.save(user_id, state)
            return state

        return self._merge_with_default(state)

    async def save(self, user_id: int, state: Dict[str, Any]) -> None:
        await self._db.connection.execute(
            """
            INSERT INTO user_state (user_id, state_json, version, updated_at)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id)
            DO UPDATE SET
                state_json = excluded.state_json,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, json.dumps(state, ensure_ascii=False)),
        )
        await self._db.connection.commit()

    async def set_active_mode(self, user_id: int, mode: str) -> Dict[str, Any]:
        state = await self.get(user_id)
        state["active_mode"] = mode
        await self.save(user_id, state)
        return state

    async def get_support_stats(self) -> Dict[str, Any]:
        cursor = await self._db.connection.execute(
            "SELECT state_json FROM user_state"
        )
        rows = await cursor.fetchall()

        totals = {
            "panic": 0,
            "flashback": 0,
            "insomnia": 0,
        }
        users_with_profile = 0

        for row in rows:
            try:
                state = json.loads(row[0])
            except Exception:
                continue

            memory_flags = state.get("memory_flags", {})
            support_profile = memory_flags.get("support_profile", {})
            support_stats = memory_flags.get("support_stats", {})
            episode_counts = support_stats.get("episode_counts", {})

            if support_profile:
                users_with_profile += 1

            for key in totals:
                totals[key] += int(episode_counts.get(key, {}).get("count", 0))

        return {
            "users_with_support_profile": users_with_profile,
            "episode_counts": totals,
        }
