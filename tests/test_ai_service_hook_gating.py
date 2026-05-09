import unittest

from services.ai_service import AIService


class AIServiceHookGatingTests(unittest.TestCase):
    def setUp(self):
        self.service = AIService(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            conversation_engine=object(),
        )

    def test_does_not_hook_plain_greeting(self):
        self.assertFalse(
            self.service._should_apply_emotional_hook(
                user_message="Привет",
                state={"emotional_tone": "neutral"},
                source="chat",
            )
        )

    def test_does_not_hook_name_recall_question(self):
        self.assertFalse(
            self.service._should_apply_emotional_hook(
                user_message="Как меня зовут?",
                state={"emotional_tone": "neutral"},
                source="chat",
            )
        )


if __name__ == "__main__":
    unittest.main()
