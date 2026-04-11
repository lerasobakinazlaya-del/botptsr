import unittest

from services.keyword_memory_service import KeywordMemoryService
from services.long_term_memory_service import LongTermMemoryService


class _FakeRepository:
    def __init__(self):
        self.memories = []
        self._next_id = 1

    async def init_table(self):
        return None

    async def upsert(self, *, user_id, category, value, weight, source_kind, commit=False):
        for memory in self.memories:
            if (
                memory["user_id"] == user_id
                and memory["category"] == category
                and memory["value"] == value
            ):
                memory["weight"] = weight
                memory["source_kind"] = source_kind
                memory["times_seen"] += 1
                return memory

        memory = {
            "id": self._next_id,
            "user_id": user_id,
            "category": category,
            "value": value,
            "weight": weight,
            "source_kind": source_kind,
            "pinned": False,
            "times_seen": 1,
            "created_at": "2026-04-11T00:00:00+00:00",
            "updated_at": "2026-04-11T00:00:00+00:00",
            "last_used_at": "2026-04-11T00:00:00+00:00",
        }
        self._next_id += 1
        self.memories.append(memory)
        return memory

    async def commit(self):
        return None

    async def get_user_memories(self, user_id, limit=80):
        return [memory for memory in self.memories if memory["user_id"] == user_id][:limit]

    async def mark_used(self, ids):
        return None

    async def delete_memories(self, ids):
        before = len(self.memories)
        id_set = set(ids)
        self.memories = [memory for memory in self.memories if memory["id"] not in id_set]
        return before - len(self.memories)


class _FakeSettingsService:
    def get_runtime_settings(self):
        return {
            "ai": {
                "long_term_memory_enabled": True,
                "long_term_memory_auto_prune_enabled": True,
                "long_term_memory_soft_limit": 60,
                "long_term_memory_max_items": 12,
            }
        }


class LongTermMemoryServiceNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_and_prompt_context_include_identity_facts(self):
        repository = _FakeRepository()
        service = LongTermMemoryService(
            repository=repository,
            keyword_memory_service=KeywordMemoryService(),
            settings_service=_FakeSettingsService(),
        )

        await service.capture_from_message(42, "Меня зовут Лена, а мою жену зовут Оля.")
        context = await service.build_prompt_context(42)

        self.assertTrue(any(memory["category"] == "identity_facts" for memory in repository.memories))
        self.assertIn("Важные имена и связи", context)
        self.assertIn("пользователя зовут Лена", context)
        self.assertIn("жену пользователя зовут Оля", context)


if __name__ == "__main__":
    unittest.main()
