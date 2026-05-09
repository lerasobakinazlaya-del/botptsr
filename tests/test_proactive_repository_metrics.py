import os
import tempfile
import unittest

from database.db import Database
from database.proactive_repository import ProactiveRepository
from database.user_preference_repository import UserPreferenceRepository
from services.user_service import UserService


class ProactiveRepositoryMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.db = Database(self.db_path)
        await self.db.connect()
        self.proactive_repository = ProactiveRepository(self.db)
        self.user_preference_repository = UserPreferenceRepository(self.db)
        self.user_service = UserService(self.db)
        await self.user_service.init_table()
        await self.proactive_repository.init_table()
        await self.user_preference_repository.init_table()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_overview_includes_reply_and_opt_out_rates(self):
        await self.db.connection.execute(
            """
            INSERT INTO messages (user_id, role, text, created_at)
            VALUES
                (1, 'user', 'hi', '2026-01-01 09:00:00'),
                (1, 'assistant', 'ping', '2026-01-01 10:00:00'),
                (2, 'user', 'hello', '2026-01-01 09:00:00'),
                (2, 'assistant', 'ping', '2026-01-01 10:00:00')
            """
        )
        await self.db.connection.execute(
            """
            INSERT INTO proactive_messages (
                user_id, trigger_kind, status, source_last_user_message_at, created_at
            )
            VALUES
                (1, 'inactivity_followup', 'sent', '2026-01-01 09:00:00', '2026-01-01 10:00:00'),
                (2, 'inactivity_followup', 'sent', '2026-01-01 09:00:00', '2026-01-01 10:00:00')
            """
        )
        await self.db.connection.execute(
            """
            INSERT INTO messages (user_id, role, text, created_at)
            VALUES
                (1, 'user', 'reply after proactive', '2026-01-01 11:00:00')
            """
        )
        await self.db.connection.execute(
            """
            INSERT INTO user_preference_events (
                user_id, event_kind, proactive_enabled, timezone, created_at
            )
            VALUES
                (2, 'proactive_enabled', 0, NULL, '2026-01-02 10:00:00')
            """
        )
        await self.db.connection.commit()

        overview = await self.proactive_repository.get_overview()

        self.assertEqual(overview["sent_total"], 2)
        self.assertEqual(overview["reply_after_proactive_total"], 1)
        self.assertEqual(overview["reply_after_proactive_rate"], 50.0)
        self.assertEqual(overview["opt_out_after_proactive_total"], 1)
        self.assertEqual(overview["opt_out_after_proactive_rate"], 50.0)
        self.assertEqual(overview["status_breakdown_total"], {})
        self.assertEqual(overview["recent_failures"], [])

    async def test_overview_breaks_down_non_sent_statuses(self):
        await self.db.connection.execute(
            """
            INSERT INTO proactive_messages (
                user_id, trigger_kind, status, source_last_user_message_at, created_at, error_text
            )
            VALUES
                (1, 'inactivity_followup', 'failed', '2026-01-01 09:00:00', CURRENT_TIMESTAMP, 'telegram_forbidden'),
                (2, 'reengagement', 'blocked', '2026-01-01 09:00:00', CURRENT_TIMESTAMP, 'quiet_hours'),
                (3, 'reengagement', 'persist_failed', '2026-01-01 09:00:00', CURRENT_TIMESTAMP, 'db_persist_failed')
            """
        )
        await self.db.connection.commit()

        overview = await self.proactive_repository.get_overview()

        self.assertEqual(overview["failed_total"], 3)
        self.assertEqual(overview["status_breakdown_total"]["failed"], 1)
        self.assertEqual(overview["status_breakdown_total"]["blocked"], 1)
        self.assertEqual(overview["status_breakdown_total"]["persist_failed"], 1)
        self.assertEqual(overview["status_breakdown_7d"]["failed"], 1)
        self.assertEqual(overview["recent_failures"][0]["status"], "persist_failed")
        self.assertEqual(overview["recent_failures"][-1]["error_text"], "telegram_forbidden")

    async def test_event_timeline_includes_user_and_nearby_messages(self):
        await self.db.connection.execute(
            """
            INSERT INTO users (id, username, first_name, active_mode, subscription_plan, is_premium, is_admin)
            VALUES (1, 'valera', 'Валера', 'base', 'free', 0, 0)
            """
        )
        await self.db.connection.execute(
            """
            INSERT INTO messages (user_id, role, text, created_at)
            VALUES
                (1, 'user', 'Последний вопрос пользователя', '2026-01-01 09:00:00'),
                (1, 'assistant', 'Бот пишет первым из памяти', '2026-01-01 10:00:02')
            """
        )
        await self.db.connection.execute(
            """
            INSERT INTO proactive_messages (
                user_id, trigger_kind, status, source_last_user_message_at, created_at
            )
            VALUES
                (1, 'reengagement', 'sent', '2026-01-01T09:00:00+00:00', '2026-01-01 10:00:00')
            """
        )
        await self.db.connection.commit()

        timeline = await self.proactive_repository.get_event_timeline(limit=10)

        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["first_name"], "Валера")
        self.assertEqual(timeline[0]["assistant_text"], "Бот пишет первым из памяти")
        self.assertEqual(timeline[0]["last_user_text"], "Последний вопрос пользователя")

    async def test_counts_events_for_same_silence(self):
        await self.db.connection.execute(
            """
            INSERT INTO proactive_messages (
                user_id, trigger_kind, status, source_last_user_message_at, created_at
            )
            VALUES
                (1, 'reengagement', 'sent', '2026-01-01T09:00:00+00:00', '2026-01-01 10:00:00'),
                (1, 'reengagement', 'send_failed', '2026-01-01T09:00:00+00:00', '2026-01-02 10:00:00'),
                (1, 'reengagement', 'sent', '2026-01-03T09:00:00+00:00', '2026-01-03 10:00:00')
            """
        )
        await self.db.connection.commit()

        count = await self.proactive_repository.count_events_for_silence(
            user_id=1,
            source_last_user_message_at="2026-01-01T09:00:00+00:00",
        )

        self.assertEqual(count, 2)
