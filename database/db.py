from contextlib import asynccontextmanager
from typing import Awaitable, Callable

import aiosqlite


class Database:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self.connection = None
        self._schema_migrations: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
            ("001_add_user_memories_pinned", self._migration_add_user_memories_pinned),
        ]

    async def connect(self):
        self.connection = await aiosqlite.connect(self.db_path)
        await self._configure()
        await self.create_tables()
        await self._ensure_schema_metadata()
        await self.run_migrations()

    async def _configure(self):
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA synchronous=NORMAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.execute("PRAGMA busy_timeout=5000")
        await self.connection.commit()

    async def create_tables(self):
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                text TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                external_payment_id TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'RUB',
                status TEXT NOT NULL,
                is_first_payment INTEGER NOT NULL DEFAULT 0,
                paid_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                metadata_json TEXT NULL,
                UNIQUE(provider, external_payment_id)
            )
            """
        )
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_user_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                reward_amount_minor_units INTEGER NOT NULL DEFAULT 0,
                external_payment_id TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                converted_at TIMESTAMP NULL,
                rewarded_at TIMESTAMP NULL
            )
            """
        )
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monetization_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_name TEXT NOT NULL,
                offer_trigger TEXT NULL,
                offer_variant TEXT NULL,
                payment_external_id TEXT NULL,
                metadata_json TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NULL,
                source TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NULL,
                completion_tokens INTEGER NULL,
                total_tokens INTEGER NULL,
                reasoning_tokens INTEGER NULL,
                cached_tokens INTEGER NULL,
                estimated_cost_usd REAL NULL,
                latency_ms REAL NULL,
                finish_reason TEXT NULL,
                request_user TEXT NULL,
                metadata_json TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_user_id_id
            ON messages (user_id, id DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_user_id_created_at
            ON messages (user_id, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_payments_user_id_paid_at
            ON payments (user_id, paid_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_payments_status_paid_at
            ON payments (status, paid_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_referrals_referrer_status
            ON referrals (referrer_user_id, status, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_referrals_referred_status
            ON referrals (referred_user_id, status, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_monetization_events_name_created
            ON monetization_events (event_name, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_monetization_events_user_created
            ON monetization_events (user_id, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_openai_usage_source_created
            ON openai_usage_events (source, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_openai_usage_user_created
            ON openai_usage_events (user_id, created_at DESC)
            """
        )
        await self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_openai_usage_model_created
            ON openai_usage_events (model, created_at DESC)
            """
        )
        await self.connection.commit()

    async def _ensure_schema_metadata(self) -> None:
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self.connection.execute(
            """
            INSERT OR IGNORE INTO schema_version (id, version)
            VALUES (1, 0)
            """
        )
        await self.connection.commit()

    async def get_schema_version(self) -> int:
        if self.connection is None:
            return 0

        cursor = await self.connection.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        )
        row = await cursor.fetchone()
        return int(row[0] or 0) if row else 0

    async def set_schema_version(self, version: int) -> None:
        if self.connection is None:
            return

        await self.connection.execute(
            """
            UPDATE schema_version
            SET version = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (int(version),),
        )
        await self.connection.commit()

    async def run_migrations(self) -> None:
        if self.connection is None:
            return

        await self._ensure_schema_metadata()
        current_version = await self.get_schema_version()
        for version, (_, migration) in enumerate(self._schema_migrations, start=1):
            if version <= current_version:
                continue
            applied = await migration()
            if not applied:
                continue
            await self.set_schema_version(version)

    async def _migration_add_user_memories_pinned(self) -> bool:
        cursor = await self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_memories'"
        )
        if await cursor.fetchone() is None:
            return False

        cursor = await self.connection.execute("PRAGMA table_info(user_memories)")
        columns = await cursor.fetchall()
        if any(column[1] == "pinned" for column in columns):
            return True

        await self.connection.execute(
            "ALTER TABLE user_memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
        )
        await self.connection.commit()
        return True

    async def close(self):
        if self.connection is not None:
            await self.connection.close()

    async def commit(self) -> None:
        if self.connection is not None:
            await self.connection.commit()

    async def rollback(self) -> None:
        if self.connection is not None:
            await self.connection.rollback()

    @asynccontextmanager
    async def transaction(self):
        try:
            yield self.connection
            await self.commit()
        except Exception:
            await self.rollback()
            raise
