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
                    "last_user_mood": "подъём или хорошее настроение",
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

    def test_reengagement_prompt_rotates_starter_family(self):
        prompt = self.service.build_reengagement_prompt(
            {
                "relationship_state": {
                    "last_user_topic": "work",
                    "callback_candidates": ["new project move"],
                    "warmth": 0.4,
                    "playfulness": 0.3,
                },
                "reengagement": {
                    "sent_count": 1,
                },
            },
            hours_silent=18,
            active_mode="free_talk",
        )

        self.assertIn("opener family: callback_thread", prompt)
        self.assertIn("callback_thread", prompt)

    def test_reengagement_prompt_includes_stage_guidance_and_name_hint(self):
        prompt = self.service.build_reengagement_prompt(
            {
                "relationship_state": {
                    "last_user_topic": "work",
                    "last_user_mood": "подъём или хорошее настроение",
                },
                "user_profile": {
                    "identity_facts": ["пользователя зовут Лена"],
                },
            },
            hours_silent=200,
            active_mode="base",
        )

        self.assertIn("Retention stage: day_7_reset", prompt)
        self.assertIn("user's name: Лена", prompt)
        self.assertIn("Last notable mood: подъём или хорошее настроение", prompt)

    def test_reengagement_message_increments_sent_count(self):
        updated = self.service.apply_assistant_message(
            {
                "relationship_state": {},
                "reengagement": {"sent_count": 2},
            },
            "Hi",
            source="reengagement",
        )

        self.assertEqual(updated["reengagement"]["sent_count"], 3)

    def test_name_facts_are_saved_into_profile(self):
        state = self.service.apply_user_message(
            {},
            "Меня зовут Лена, а мою жену зовут Оля.",
        )

        self.assertIn("пользователя зовут Лена", state["user_profile"]["identity_facts"])
        self.assertIn("жену пользователя зовут Оля", state["user_profile"]["identity_facts"])

    def test_prompt_context_mentions_saved_names(self):
        state = self.service.apply_user_message(
            {},
            "Меня зовут Лена, а мою подругу зовут Маша.",
        )

        context = self.service.build_prompt_context(state)

        self.assertIn("Важные имена и связи", context)
        self.assertIn("пользователя зовут Лена", context)
        self.assertIn("подругу пользователя зовут Маша", context)


    def test_reengagement_context_returns_name_and_mood(self):
        context = self.service.get_reengagement_context(
            {
                "relationship_state": {
                    "last_user_topic": "отношения",
                    "last_user_mood": "нужда в контакте или тепле",
                },
                "user_profile": {
                    "identity_facts": ["пользователя зовут Аня"],
                },
            }
        )

        self.assertEqual(context["topic"], "отношения")
        self.assertEqual(context["name_hint"], "Аня")
        self.assertEqual(context["last_mood"], "нужда в контакте или тепле")


if __name__ == "__main__":
    unittest.main()
