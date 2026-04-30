import os
import tempfile
import unittest

from database.db import Database
from database.openai_usage_repository import OpenAIUsageRepository


class OpenAIUsageRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "usage.db")
        self.db = Database(self.db_path)
        await self.db.connect()
        await self.db.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT
            )
            """
        )
        await self.db.connection.commit()
        self.repository = OpenAIUsageRepository(self.db)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_overview_groups_usage_by_source_and_model(self):
        await self.db.connection.execute(
            "INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)",
            (1, "alice", "Alice"),
        )
        await self.db.connection.commit()
        await self.repository.log_event(
            user_id=1,
            source="chat",
            model="gpt-4o-mini",
            prompt_tokens=300,
            completion_tokens=120,
            total_tokens=420,
            estimated_cost_usd=0.000117,
            latency_ms=640.0,
            finish_reason="stop",
            request_user="1",
            metadata={"entrypoint": "telegram"},
        )
        await self.repository.log_event(
            user_id=1,
            source="admin_test_reply",
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            estimated_cost_usd=0.000039,
            latency_ms=220.0,
            finish_reason="stop",
            request_user="admin-live-test",
            metadata={"entrypoint": "admin"},
        )

        overview = await self.repository.get_overview()

        self.assertEqual(overview["requests_total"], 2)
        self.assertEqual(overview["tokens_total"], 560)
        self.assertEqual(overview["prompt_tokens_total"], 400)
        self.assertEqual(overview["completion_tokens_total"], 160)
        self.assertEqual(overview["users_total"], 1)
        self.assertEqual(overview["users_30d"], 1)
        self.assertEqual(overview["by_source_30d"]["chat"]["total_tokens"], 420)
        self.assertEqual(overview["by_source_30d"]["admin_test_reply"]["requests"], 1)
        self.assertEqual(overview["by_model_30d"]["gpt-4o-mini"]["requests"], 2)
        self.assertEqual(overview["recent"][0]["source"], "admin_test_reply")
        self.assertEqual(overview["recent"][0]["username"], "alice")
        self.assertEqual(overview["top_users_30d"][0]["user_id"], 1)
        self.assertEqual(overview["top_users_30d"][0]["first_name"], "Alice")
        self.assertEqual(overview["top_users_30d"][0]["total_tokens"], 560)
        self.assertEqual(overview["daily_14d"][0]["requests"], 2)
