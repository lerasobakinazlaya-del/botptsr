import unittest
from datetime import datetime, timedelta, timezone

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

    def test_inactivity_decay_reduces_relationship_metrics(self):
        state = {
            "relationship_state": {
                "trust": 0.6,
                "warmth": 0.6,
                "playfulness": 0.4,
                "last_interaction_at": (
                    datetime.now(timezone.utc) - timedelta(days=7)
                ).isoformat(),
            }
        }

        updated = self.service.apply_assistant_message(state, "Привет")
        relationship = updated["relationship_state"]

        self.assertLess(relationship["trust"], 0.6)
        self.assertLess(relationship["warmth"], 0.6)
        self.assertLess(relationship["playfulness"], 0.4)

    def test_reengagement_blocks_repeated_callback_topic(self):
        state = {
            "reengagement": {
                "last_callback_topic": "работа",
            }
        }

        can_send = self.service.can_send_reengagement(
            state,
            min_hours_between=24,
            last_user_message_at="2026-01-01T00:00:00+00:00",
            callback_topic="работа",
        )

        self.assertFalse(can_send)


if __name__ == "__main__":
    unittest.main()
