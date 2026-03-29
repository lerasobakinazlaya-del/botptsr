import asyncio
import unittest

from services.conversation_summary_service import ConversationSummaryService


class ConversationSummaryServiceSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_refresh_serializes_same_user_tasks_and_keeps_latest_snapshot(self):
        service = ConversationSummaryService(
            client=None,
            message_repository=None,
            state_repository=None,
            settings_service=None,
        )

        calls: list[dict] = []
        active_calls = 0
        max_active_calls = 0

        async def fake_refresh(user_id, state_snapshot=None):
            nonlocal active_calls, max_active_calls
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            calls.append({"user_id": user_id, "snapshot": dict(state_snapshot or {})})
            await asyncio.sleep(0.05)
            active_calls -= 1

        service.maybe_refresh_summary = fake_refresh  # type: ignore[method-assign]

        service.schedule_refresh(42, {"interaction_count": 1})
        await asyncio.sleep(0.01)
        service.schedule_refresh(42, {"interaction_count": 2})
        service.schedule_refresh(42, {"interaction_count": 3})

        while service._user_tasks:  # type: ignore[attr-defined]
            await asyncio.gather(*list(service._user_tasks.values()))

        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[0]["snapshot"]["interaction_count"], 1)
        self.assertEqual(calls[-1]["snapshot"]["interaction_count"], 3)
        self.assertEqual(max_active_calls, 1)


if __name__ == "__main__":
    unittest.main()
