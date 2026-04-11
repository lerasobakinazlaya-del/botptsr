import unittest

from services.memory_engine import ChatMessage
from services.memory_profile_service import MemoryProfileService


class _FakeLongTermMemoryService:
    def __init__(self):
        self.calls = 0

    async def get_user_memories(self, user_id: int, limit: int = 80):
        self.calls += 1
        return [
            {
                "id": 1,
                "category": "identity_facts",
                "value": "пользователя зовут Лена",
                "updated_at": "2026-04-11T00:00:00+00:00",
                "times_seen": 2,
                "pinned": False,
            },
            {
                "id": 2,
                "category": "important_context",
                "value": "есть сложная история с тревогой",
                "updated_at": "2026-04-11T00:00:00+00:00",
                "times_seen": 1,
                "pinned": False,
            },
        ]


class _FakeRedis:
    def __init__(self):
        self.storage = {}

    async def get(self, key: str):
        return self.storage.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.storage[key] = value


class MemoryProfileServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_prompt_context_merges_state_history_and_long_term(self):
        service = MemoryProfileService(
            long_term_memory_service=_FakeLongTermMemoryService(),
            redis=None,
        )

        context = await service.build_prompt_context(
            user_id=1,
            state={
                "user_profile": {
                    "identity_facts": ["жену пользователя зовут Оля"],
                    "goals": ["разобраться с проектом"],
                    "interests": ["музыка"],
                    "personality_traits": ["любит прямой разговор"],
                    "recurring_topics": ["отношения"],
                },
                "memory_flags": {
                    "current_focus": [{"value": "завтрашний разговор"}],
                    "open_loops": [{"value": "не договорили про границы"}],
                    "recent_topics": [{"value": "поездка"}],
                    "support_profile": {
                        "support_preferences": [{"value": "лучше без длинных советов"}],
                        "coping_tools": [{"value": "душ и тишина"}],
                    },
                },
                "relationship_state": {
                    "response_preferences": {"length": "brief", "initiative": "high"},
                    "shared_threads": ["работа и отношения"],
                    "callback_candidates": ["проект"],
                },
            },
            history=[
                ChatMessage(role="user", content="Мы вчера не договорили про границы и утро после.", timestamp=1.0),
                ChatMessage(role="assistant", content="ok", timestamp=2.0),
                ChatMessage(role="user", content="И ещё я думаю про завтрашний разговор.", timestamp=3.0),
            ],
        )

        self.assertIn("Важные имена и связи", context)
        self.assertIn("пользователя зовут Лена", context)
        self.assertIn("жену пользователя зовут Оля", context)
        self.assertIn("Цели и желания", context)
        self.assertIn("Как лучше отвечать этому пользователю", context)
        self.assertIn("Незавершенные темы", context)
        self.assertIn("Последняя живая нить разговора", context)

    async def test_build_prompt_context_uses_redis_cache(self):
        long_term = _FakeLongTermMemoryService()
        redis = _FakeRedis()
        service = MemoryProfileService(
            long_term_memory_service=long_term,
            redis=redis,
        )
        state = {
            "user_profile": {"identity_facts": ["пользователя зовут Лена"]},
            "memory_flags": {},
            "relationship_state": {},
        }

        first = await service.build_prompt_context(user_id=7, state=state, history=[])
        second = await service.build_prompt_context(user_id=7, state=state, history=[])

        self.assertEqual(first, second)
        self.assertEqual(long_term.calls, 2)
        self.assertTrue(redis.storage)


if __name__ == "__main__":
    unittest.main()
