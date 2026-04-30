import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
        now = datetime.now(timezone.utc).replace(microsecond=0)
        soon_expiry = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        later_expiry = (now + timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S")
        expired_at = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        created_basic = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        created_soon = (now - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        created_later = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        created_expired = (now - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")

        await self.db.connection.executemany(
            """
            INSERT INTO users (
                id,
                username,
                first_name,
                active_mode,
                is_premium,
                subscription_plan,
                premium_expires_at,
                is_admin,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "basic", "Basic", "base", 0, "free", None, 0, created_basic),
                (2, "soon", "Soon", "base", 1, "pro", soon_expiry, 0, created_soon),
                (3, "later", "Later", "base", 1, "premium", later_expiry, 0, created_later),
                (4, "expired", "Expired", "base", 1, "premium", expired_at, 0, created_expired),
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
        await self.user_service.upsert_user_access(5, subscription_plan="pro")

        items = await self.user_service.search_users(filter_by="without_premium", limit=10)

        self.assertEqual([item["id"] for item in items], [1, 4])

    async def test_search_users_combines_query_with_without_premium_filter(self):
        items = await self.user_service.search_users(
            query="soon",
            filter_by="without_premium",
            limit=10,
        )

        self.assertEqual([], items)

    async def test_count_users_respects_filter(self):
        count = await self.user_service.count_users(filter_by="premium_active")

        self.assertEqual(count, 2)

    async def test_get_subscription_segments_overview(self):
        await self.user_service.upsert_user_access(5, subscription_plan="pro")

        segments = await self.user_service.get_subscription_segments_overview()

        self.assertEqual(
            segments,
            {
                "all": 5,
                "paid_active": 3,
                "pro_active": 2,
                "premium_active": 1,
                "paid_expiring_3d": 1,
                "paid_expired": 1,
                "free": 2,
            },
        )

    async def test_concurrent_subscription_grants_accumulate_days(self):
        await self.user_service.upsert_user_access(6)
        started_at = datetime.now(timezone.utc)

        await asyncio.gather(
            self.user_service.grant_subscription_days(6, "pro", 10),
            self.user_service.grant_subscription_days(6, "pro", 20),
        )

        user = await self.user_service.get_user(6)
        expires_at = datetime.strptime(
            user["premium_expires_at"],
            "%Y-%m-%d %H:%M:%S",
        ).replace(tzinfo=timezone.utc)
        self.assertGreaterEqual(expires_at, started_at + timedelta(days=29, hours=23))
