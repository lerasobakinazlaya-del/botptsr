import os
import tempfile
import unittest
import asyncio

from database.db import Database


class DatabaseMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_migrations_adds_pinned_column_and_advances_schema_version(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db = None
        try:
            handle.close()
            db = Database(db_path=handle.name)
            await db.connect()

            await db.connection.execute(
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
                    UNIQUE(user_id, category, normalized_value)
                )
                """
            )
            await db.connection.commit()

            await db.run_migrations()

            cursor = await db.connection.execute("PRAGMA table_info(user_memories)")
            columns = await cursor.fetchall()
            self.assertTrue(any(column[1] == "pinned" for column in columns))
            self.assertEqual(await db.get_schema_version(), 1)
        finally:
            if db is not None:
                await db.close()
            if os.path.exists(handle.name):
                os.unlink(handle.name)


class DatabaseTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.handle.close()
        self.db = Database(db_path=self.handle.name)
        await self.db.connect()
        await self.db.connection.execute(
            "CREATE TABLE IF NOT EXISTS transaction_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        await self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close()
        if os.path.exists(self.handle.name):
            os.unlink(self.handle.name)

    async def test_transaction_serializes_concurrent_writers(self):
        first_can_commit = asyncio.Event()
        second_started = asyncio.Event()

        async def second_writer():
            async with self.db.transaction():
                second_started.set()
                await self.db.connection.execute(
                    "INSERT INTO transaction_probe (id, value) VALUES (2, 'second')"
                )

        async with self.db.transaction():
            await self.db.connection.execute(
                "INSERT INTO transaction_probe (id, value) VALUES (1, 'first')"
            )
            task = asyncio.create_task(second_writer())
            await asyncio.sleep(0.05)
            self.assertFalse(second_started.is_set())
            first_can_commit.set()

        await first_can_commit.wait()
        await task

        cursor = await self.db.connection.execute(
            "SELECT id FROM transaction_probe ORDER BY id"
        )
        rows = await cursor.fetchall()
        self.assertEqual([(1,), (2,)], rows)

    async def test_nested_transaction_reuses_outer_transaction(self):
        with self.assertRaises(RuntimeError):
            async with self.db.transaction():
                await self.db.connection.execute(
                    "INSERT INTO transaction_probe (id, value) VALUES (1, 'outer')"
                )
                async with self.db.transaction():
                    await self.db.connection.execute(
                        "INSERT INTO transaction_probe (id, value) VALUES (2, 'inner')"
                    )
                raise RuntimeError("rollback all")

        cursor = await self.db.connection.execute("SELECT COUNT(*) FROM transaction_probe")
        row = await cursor.fetchone()
        self.assertEqual(0, row[0])


if __name__ == "__main__":
    unittest.main()
