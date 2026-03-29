import unittest

from services.human_memory_service import HumanMemoryService


class HumanMemoryServiceModeTests(unittest.TestCase):
    def setUp(self):
        self.service = HumanMemoryService()

    def test_base_can_adapt_to_comfort_for_heavy_mood(self):
        suggested = self.service.suggest_mode(
            {
                "relationship_state": {
                    "last_user_mood": "тревога или внутреннее напряжение",
                    "last_user_topic": "отношения",
                }
            },
            "base",
        )

        self.assertEqual(suggested, "comfort")

    def test_explicit_comfort_mode_is_not_silently_downgraded(self):
        suggested = self.service.suggest_mode(
            {
                "relationship_state": {
                    "last_user_mood": "подъем или хорошее настроение",
                    "last_user_topic": "отдых",
                }
            },
            "comfort",
        )

        self.assertEqual(suggested, "comfort")


if __name__ == "__main__":
    unittest.main()
