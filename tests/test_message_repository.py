import os
import tempfile
import unittest

from database.db import Database
from database.repository import MessageRepository


class MessageRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "messages.db")
        self.db = Database(self.db_path)
        await self.db.connect()
        self.repository = MessageRepository(self.db)

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_current_month_count_tracks_user_messages_only(self):
        await self.repository.save(1, "user", "one")
        await self.repository.save(1, "assistant", "reply")
        await self.repository.save(1, "user", "two")
        await self.repository.save(2, "user", "other user")

        today_count = await self.repository.get_user_messages_count_today(1)
        month_count = await self.repository.get_user_messages_count_current_month(1)

        self.assertEqual(2, today_count)
        self.assertEqual(2, month_count)


if __name__ == "__main__":
    unittest.main()
