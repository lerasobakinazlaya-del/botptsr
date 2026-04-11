import unittest

from services.keyword_memory_service import KeywordMemoryService


class KeywordMemoryServiceNameTests(unittest.TestCase):
    def setUp(self):
        self.service = KeywordMemoryService()

    def test_extract_memory_candidates_capture_identity_facts(self):
        result = self.service.extract_memory_candidates(
            "Меня зовут Лена, а мою подругу зовут Маша."
        )

        self.assertIn("identity_facts", result)
        self.assertIn("пользователя зовут Лена", result["identity_facts"])
        self.assertIn("подругу пользователя зовут Маша", result["identity_facts"])

    def test_build_prompt_context_includes_identity_facts(self):
        state = self.service.apply({}, "Меня зовут Лена, а мою жену зовут Оля.")

        context = self.service.build_prompt_context(state)

        self.assertIn("Важные имена и связи", context)
        self.assertIn("пользователя зовут Лена", context)
        self.assertIn("жену пользователя зовут Оля", context)


if __name__ == "__main__":
    unittest.main()
