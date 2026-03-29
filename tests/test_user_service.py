import tempfile
import unittest
from pathlib import Path

from database.db import Database
from services.user_service import UserService


class UserServiceSortingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_users.db"
        self.db = Database(str(self.db_path))
        await self.db.connect()
        self.user_service = UserService(self.db)
        await self.user_service.init_table()

        await self.db.connection.executemany(
            """
            INSERT INTO users (
                id,
                username,
                first_name,
                active_mode,
                is_premium,
                premium_expires_at,
                is_admin,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "basic", "Basic", "base", 0, None, 0, "2026-03-25 10:00:00"),
                (2, "soon", "Soon", "base", 1, "2026-03-30 10:00:00", 0, "2026-03-26 10:00:00"),
                (3, "later", "Later", "base", 1, "2026-04-10 10:00:00", 0, "2026-03-27 10:00:00"),
                (4, "expired", "Expired", "base", 1, "2026-03-20 10:00:00", 0, "2026-03-24 10:00:00"),
            ],
        )
        await self.db.connection.commit()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp_dir.cleanup()

    async def test_search_users_sorts_by_premium_expiry_ascending(self):
        items = await self.user_service.search_users(sort_by="premium_expiry_asc", limit=10)

        self.assertEqual([item["id"] for item in items], [2, 3, 4, 1])

    async def test_search_users_sorts_active_premium_first(self):
        items = await self.user_service.search_users(sort_by="premium_active_first", limit=10)

        self.assertEqual([item["id"] for item in items], [2, 3, 1, 4])

    async def test_search_users_filters_expiring_premium(self):
        items = await self.user_service.search_users(filter_by="premium_expiring_3d", limit=10)

        self.assertEqual([item["id"] for item in items], [2])

    async def test_search_users_filters_without_premium(self):
        items = await self.user_service.search_users(filter_by="without_premium", limit=10)

        self.assertEqual([item["id"] for item in items], [1, 4])
