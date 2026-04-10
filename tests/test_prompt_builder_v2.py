import unittest
from pathlib import Path

from services.admin_settings_service import AdminSettingsService
from services.prompt_builder_v2 import PromptBuilderV2


class PromptBuilderV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = AdminSettingsService(base_dir=Path(__file__).resolve().parents[1])
        cls.prompt_builder = PromptBuilderV2(cls.settings)
        cls.templates = cls.settings.get_prompt_templates()

    def test_build_system_prompt_includes_intent_block_and_keeps_engagement_rules(self):
        prompt = self.prompt_builder.build_system_prompt(
            state={"active_mode": "base", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="base",
            memory_context="",
            user_message="Can you help me plan this?",
            intent_snapshot={
                "intent": "direct_answer",
                "desired_length": "brief",
                "needs_clarification": False,
                "should_end_with_question": False,
                "use_memory": True,
            },
        )

        self.assertIn("Тип запроса: direct_answer.", prompt)
        self.assertIn("Предпочтительная длина: brief.", prompt)
        self.assertIn(self.templates["engagement_rules"], prompt)

    def test_build_system_prompt_can_skip_memory_block_when_intent_disables_memory(self):
        prompt = self.prompt_builder.build_system_prompt(
            state={"active_mode": "base", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="base",
            memory_context="- Preferences: tea and books",
            user_message="Hi",
            intent_snapshot={
                "intent": "smalltalk",
                "desired_length": "brief",
                "needs_clarification": False,
                "should_end_with_question": True,
                "use_memory": False,
            },
        )

        self.assertNotIn("tea and books", prompt)
        self.assertNotIn(self.templates["memory_intro"], prompt)

    def test_prompt_templates_default_to_feminine_self_reference(self):
        self.assertIn("используй женский род", self.templates["personality_core"])
        self.assertIn("используй женский род", self.templates["final_instruction"])
        self.assertIn("характер Лиры", self.templates["final_instruction"])


if __name__ == "__main__":
    unittest.main()
