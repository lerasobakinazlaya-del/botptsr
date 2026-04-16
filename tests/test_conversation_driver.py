import unittest

from services.conversation_driver import (
    apply_driver_guardrails,
    build_followup,
    detect_intent,
)


class ConversationDriverTests(unittest.TestCase):
    def test_detect_intent_covers_core_categories(self):
        cases = {
            "Меня к этому тянет все сильнее": "desire",
            "Мне тревожно и как-то стыдно от этого": "emotion",
            "Представь сценарий, где я теряю контроль": "fantasy",
            "Не хочу сейчас туда идти": "resistance",
            "Почему это вообще так цепляет?": "curiosity",
            "может быть": "short_reply",
            "Скажи прямо, что мне ответить": "explicit_request",
            "Я не понимаю, что ты имеешь в виду": "confusion",
        }

        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(detect_intent(message), expected)

    def test_build_followup_returns_reflection_and_fork_question(self):
        result = build_followup(
            "fantasy",
            {
                "interest": 0.74,
                "attraction": 0.31,
                "interaction_count": 6,
                "emotional_tone": "neutral",
            },
        )

        self.assertIn("?", result)
        self.assertIn("или", result)
        self.assertLessEqual(len(result.split("?")), 2)

    def test_apply_driver_guardrails_flattens_lists_and_adds_question(self):
        result = apply_driver_guardrails(
            "1. Это уже не про любопытство.\n2. Там есть риск сорваться в чужой сценарий.",
            user_message="Меня это цепляет",
            state={"emotional_tone": "neutral"},
            intent="desire",
        )

        self.assertNotIn("1.", result)
        self.assertNotIn("2.", result)
        self.assertIn("?", result)


if __name__ == "__main__":
    unittest.main()
