import asyncio
import unittest

from services.chat_session_service import ChatSessionService


class ChatSessionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_session_serializes_same_user_requests(self):
        service = ChatSessionService()
        order: list[str] = []

        async def first():
            async with service.user_session(42):
                order.append("first-start")
                await asyncio.sleep(0.05)
                order.append("first-end")

        async def second():
            await asyncio.sleep(0.01)
            async with service.user_session(42):
                order.append("second-start")
                order.append("second-end")

        await asyncio.gather(first(), second())

        stats = service.get_runtime_stats()
        self.assertEqual(order, ["first-start", "first-end", "second-start", "second-end"])
        self.assertEqual(stats["wait_events"], 1)
        self.assertGreaterEqual(stats["max_wait_ms"], 1)


if __name__ == "__main__":
    unittest.main()
