import unittest

from handlers.chat import _build_name_recall_response


class ChatIdentityRecallTests(unittest.TestCase):
    def test_uses_saved_profile_name_before_model_call(self):
        response = _build_name_recall_response(
            user_text="Как меня зовут?",
            user={"first_name": "TelegramName"},
            state={
                "user_profile": {
                    "identity_facts": ["пользователя зовут Валера"],
                },
            },
        )

        self.assertEqual(response, "Тебя зовут Валера.")

    def test_falls_back_to_telegram_first_name(self):
        response = _build_name_recall_response(
            user_text="Помнишь мое имя?",
            user={"first_name": "Валера"},
            state={},
        )

        self.assertEqual(
            response,
            "В Telegram вижу имя: Валера. Буду обращаться к тебе так, если это ок.",
        )

    def test_uses_long_term_memory_before_telegram_name(self):
        response = _build_name_recall_response(
            user_text="Как меня зовут?",
            user={"first_name": "TelegramName"},
            state={},
            long_term_memories=[
                {
                    "category": "summary_open_loops",
                    "value": "Валера не уточнил, как он будет заботиться о себе.",
                },
                {
                    "category": "summary_response_hint",
                    "value": "Спросить, как Валера планирует обсудить идеи с женой.",
                },
            ],
        )

        self.assertEqual(response, "Тебя зовут Валера.")

    def test_ignores_unrelated_messages(self):
        response = _build_name_recall_response(
            user_text="Привет",
            user={"first_name": "Валера"},
            state={},
        )

        self.assertIsNone(response)


if __name__ == "__main__":
    unittest.main()
