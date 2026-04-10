import unittest
from pathlib import Path

from services.admin_settings_service import AdminSettingsService
from services.conversation_engine_v2 import ConversationEngineV2
from services.memory_engine import ChatMessage


class ConversationEngineV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = AdminSettingsService(base_dir=Path(__file__).resolve().parents[1])
        cls.engine = ConversationEngineV2(settings)

    def test_script_request_prefers_ready_wording(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "dominant", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="dominant",
            user_message="Скажи прямо и дословно, что сказать утром за завтраком.",
            history=[],
        )

        self.assertIn("give exact wording", prompt)
        self.assertIn("Give ready-to-send lines or a ready-to-say script.", prompt)
        self.assertIn("Do not give 'themes for discussion'", prompt)

    def test_continuation_request_uses_next_list_number_for_chat_message_objects(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "free_talk", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="free_talk",
            user_message="Ок дальше",
            history=[
                ChatMessage(
                    role="assistant",
                    content="1. Сначала скажи, что всем неловко.\n2. Потом зафиксируй, что ничего не нужно решать на бегу.",
                    timestamp=1.0,
                )
            ],
        )

        self.assertIn("Continue directly from item 3", prompt)


if __name__ == "__main__":
    unittest.main()
