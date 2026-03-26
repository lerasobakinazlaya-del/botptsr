from typing import Any


class MemoryRepository:
    def __init__(self, db):
        self.db = db

    async def commit(self) -> None:
        await self.db.connection.commit()

    async def init_table(self) -> None:
        await self.db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                value TEXT NOT NULL,
                normalized_value TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                source_kind TEXT NOT NULL DEFAULT 'message',
                times_seen INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, category, normalized_value)
            )
            """
        )
        await self._ensure_column("pinned", "INTEGER NOT NULL DEFAULT 0")
        await self.db.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_memories_user_category_updated
            ON user_memories (user_id, category, updated_at DESC)
            """
        )
        await self.db.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_memories_user_weight_updated
            ON user_memories (user_id, weight DESC, updated_at DESC)
            """
        )
        await self.db.connection.commit()

    async def _ensure_column(self, name: str, definition: str) -> None:
        cursor = await self.db.connection.execute("PRAGMA table_info(user_memories)")
        columns = await cursor.fetchall()
        if any(column[1] == name for column in columns):
            return

        await self.db.connection.execute(
            f"ALTER TABLE user_memories ADD COLUMN {name} {definition}"
        )

    async def upsert(
        self,
        user_id: int,
        category: str,
        value: str,
        *,
        weight: float = 1.0,
        source_kind: str = "message",
        commit: bool = True,
    ) -> None:
        cleaned_value = " ".join(str(value or "").split()).strip()[:220]
        if not cleaned_value:
            return

        normalized_value = cleaned_value.casefold()
        await self.db.connection.execute(
            """
            INSERT INTO user_memories (
                user_id,
                category,
                value,
                normalized_value,
                weight,
                source_kind,
                times_seen,
                created_at,
                updated_at,
                pinned
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)
            ON CONFLICT(user_id, category, normalized_value)
            DO UPDATE SET
                value = excluded.value,
                weight = MIN(25.0, user_memories.weight + excluded.weight),
                source_kind = excluded.source_kind,
                times_seen = user_memories.times_seen + 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                category,
                cleaned_value,
                normalized_value,
                float(weight),
                source_kind,
            ),
        )
        if commit:
            await self.db.connection.commit()

    async def get_user_memories(
        self,
        user_id: int,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 500))
        cursor = await self.db.connection.execute(
            """
            SELECT
                id,
                category,
                value,
                weight,
                source_kind,
                times_seen,
                created_at,
                updated_at,
                last_used_at,
                pinned
            FROM user_memories
            WHERE user_id = ?
            ORDER BY pinned DESC, weight DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, safe_limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "category": row[1],
                "value": row[2],
                "weight": float(row[3] or 0.0),
                "source_kind": row[4],
                "times_seen": int(row[5] or 0),
                "created_at": row[6],
                "updated_at": row[7],
                "last_used_at": row[8],
                "pinned": bool(row[9]),
            }
            for row in rows
        ]

    async def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        cursor = await self.db.connection.execute(
            """
            SELECT
                id,
                user_id,
                category,
                value,
                normalized_value,
                weight,
                source_kind,
                times_seen,
                created_at,
                updated_at,
                last_used_at,
                pinned
            FROM user_memories
            WHERE id = ?
            LIMIT 1
            """,
            (int(memory_id),),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "category": row[2],
            "value": row[3],
            "normalized_value": row[4],
            "weight": float(row[5] or 0.0),
            "source_kind": row[6],
            "times_seen": int(row[7] or 0),
            "created_at": row[8],
            "updated_at": row[9],
            "last_used_at": row[10],
            "pinned": bool(row[11]),
        }

    async def create_memory(
        self,
        user_id: int,
        category: str,
        value: str,
        *,
        weight: float,
        source_kind: str = "manual",
        pinned: bool = False,
    ) -> dict[str, Any]:
        cleaned_value = " ".join(str(value or "").split()).strip()[:220]
        if not cleaned_value:
            raise ValueError("Memory value is required")

        normalized_value = cleaned_value.casefold()
        existing = await self._find_existing_memory(
            user_id=user_id,
            category=category,
            normalized_value=normalized_value,
        )
        if existing is not None:
            await self.db.connection.execute(
                """
                UPDATE user_memories
                SET
                    value = ?,
                    weight = ?,
                    source_kind = ?,
                    pinned = ?,
                    times_seen = times_seen + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    cleaned_value,
                    float(weight),
                    source_kind,
                    1 if pinned else 0,
                    int(existing["id"]),
                ),
            )
            await self.db.connection.commit()
            return await self.get_memory(int(existing["id"]))

        cursor = await self.db.connection.execute(
            """
            INSERT INTO user_memories (
                user_id,
                category,
                value,
                normalized_value,
                weight,
                source_kind,
                times_seen,
                created_at,
                updated_at,
                pinned
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
            """,
            (
                int(user_id),
                category,
                cleaned_value,
                normalized_value,
                float(weight),
                source_kind,
                1 if pinned else 0,
            ),
        )
        await self.db.connection.commit()
        return await self.get_memory(int(cursor.lastrowid))

    async def update_memory(
        self,
        memory_id: int,
        *,
        category: str,
        value: str,
        weight: float,
        pinned: bool,
        source_kind: str | None = None,
    ) -> dict[str, Any] | None:
        current = await self.get_memory(memory_id)
        if current is None:
            return None

        cleaned_value = " ".join(str(value or "").split()).strip()[:220]
        if not cleaned_value:
            raise ValueError("Memory value is required")

        normalized_value = cleaned_value.casefold()
        existing = await self._find_existing_memory(
            user_id=int(current["user_id"]),
            category=category,
            normalized_value=normalized_value,
            exclude_memory_id=memory_id,
        )
        if existing is not None:
            merged_weight = max(float(existing["weight"]), float(weight))
            merged_seen = int(existing["times_seen"]) + int(current["times_seen"])
            await self.db.connection.execute(
                """
                UPDATE user_memories
                SET
                    value = ?,
                    weight = ?,
                    source_kind = ?,
                    pinned = ?,
                    times_seen = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    cleaned_value,
                    merged_weight,
                    source_kind or current["source_kind"] or existing["source_kind"],
                    1 if (pinned or bool(existing["pinned"])) else 0,
                    merged_seen,
                    int(existing["id"]),
                ),
            )
            await self.db.connection.execute(
                "DELETE FROM user_memories WHERE id = ?",
                (int(memory_id),),
            )
            await self.db.connection.commit()
            return await self.get_memory(int(existing["id"]))

        await self.db.connection.execute(
            """
            UPDATE user_memories
            SET
                category = ?,
                value = ?,
                normalized_value = ?,
                weight = ?,
                source_kind = ?,
                pinned = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                category,
                cleaned_value,
                normalized_value,
                float(weight),
                source_kind or current["source_kind"],
                1 if pinned else 0,
                int(memory_id),
            ),
        )
        await self.db.connection.commit()
        return await self.get_memory(int(memory_id))

    async def mark_used(self, memory_ids: list[int]) -> None:
        filtered_ids = [int(memory_id) for memory_id in memory_ids if memory_id]
        if not filtered_ids:
            return

        placeholders = ", ".join("?" for _ in filtered_ids)
        await self.db.connection.execute(
            f"""
            UPDATE user_memories
            SET last_used_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            filtered_ids,
        )
        await self.db.connection.commit()

    async def set_pinned(self, memory_id: int, value: bool) -> None:
        await self.db.connection.execute(
            """
            UPDATE user_memories
            SET pinned = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if value else 0, int(memory_id)),
        )
        await self.db.connection.commit()

    async def delete_memory(self, memory_id: int) -> bool:
        cursor = await self.db.connection.execute(
            "DELETE FROM user_memories WHERE id = ?",
            (int(memory_id),),
        )
        await self.db.connection.commit()
        return cursor.rowcount > 0

    async def delete_memories(self, memory_ids: list[int]) -> int:
        filtered_ids = [int(memory_id) for memory_id in memory_ids if memory_id]
        if not filtered_ids:
            return 0

        placeholders = ", ".join("?" for _ in filtered_ids)
        cursor = await self.db.connection.execute(
            f"DELETE FROM user_memories WHERE id IN ({placeholders})",
            filtered_ids,
        )
        await self.db.connection.commit()
        return int(cursor.rowcount or 0)

    async def _find_existing_memory(
        self,
        *,
        user_id: int,
        category: str,
        normalized_value: str,
        exclude_memory_id: int | None = None,
    ) -> dict[str, Any] | None:
        query = """
            SELECT
                id,
                user_id,
                category,
                value,
                normalized_value,
                weight,
                source_kind,
                times_seen,
                created_at,
                updated_at,
                last_used_at,
                pinned
            FROM user_memories
            WHERE user_id = ? AND category = ? AND normalized_value = ?
        """
        params: list[Any] = [int(user_id), category, normalized_value]
        if exclude_memory_id is not None:
            query += " AND id != ?"
            params.append(int(exclude_memory_id))
        query += " ORDER BY id DESC LIMIT 1"

        cursor = await self.db.connection.execute(query, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "category": row[2],
            "value": row[3],
            "normalized_value": row[4],
            "weight": float(row[5] or 0.0),
            "source_kind": row[6],
            "times_seen": int(row[7] or 0),
            "created_at": row[8],
            "updated_at": row[9],
            "last_used_at": row[10],
            "pinned": bool(row[11]),
        }
