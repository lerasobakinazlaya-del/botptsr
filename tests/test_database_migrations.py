import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
