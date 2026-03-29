import unittest
from difflib import SequenceMatcher
from pathlib import Path

from services.admin_settings_service import AdminSettingsService
from services.ai_profile_service import resolve_ai_profile
from services.prompt_builder import PromptBuilder


class PromptBuilderModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = AdminSettingsService(base_dir=Path(__file__).resolve().parents[1])
        cls.prompt_builder = PromptBuilder(cls.settings)
        cls.base_state = {
            "interaction_count": 9,
            "conversation_phase": "trust",
            "interest": 0.62,
            "control": 0.78,
            "attraction": 0.22,
            "fatigue": 0.12,
            "irritation": 0.05,
            "emotional_tone": "reflective",
        }
        cls.user_message = "Мне тревожно, но я хочу спокойно разобраться, что со мной происходит."

    def _build_prompt(self, mode_name: str) -> str:
        return self.prompt_builder.build_system_prompt(
            state=self.base_state | {"active_mode": mode_name},
            access_level="analysis",
            active_mode=mode_name,
            memory_context="",
            user_message=self.user_message,
        )

    def test_mode_specific_contracts_are_present(self):
        expectations = {
            "base": "Базовый режим не тянет внимание на себя",
            "comfort": "В режиме поддержки сначала снижаешь внутреннее напряжение пользователя",
            "mentor": "В режиме наставника ты собираешь мысли пользователя в ясную рамку",
            "passion": "В режиме близости держишь теплое притяжение и деликатный флирт",
            "night": "В полуночном режиме ты звучишь медленнее, увереннее и темнее",
            "free_talk": "В свободном режиме звучишь как живой взрослый человек",
            "dominant": "В доминирующем режиме ты звучишь собранно, ведущ",
        }

        for mode_name, expected in expectations.items():
            with self.subTest(mode=mode_name):
                prompt = self._build_prompt(mode_name)
                self.assertIn(expected, prompt)

    def test_mode_prompts_are_meaningfully_distinct_from_base(self):
        base_prompt = self._build_prompt("base")
        thresholds = {
            "comfort": 0.92,
            "passion": 0.93,
            "mentor": 0.93,
            "night": 0.93,
            "free_talk": 0.84,
            "dominant": 0.93,
        }

        for mode_name, max_ratio in thresholds.items():
            with self.subTest(mode=mode_name):
                prompt = self._build_prompt(mode_name)
                similarity = SequenceMatcher(None, base_prompt, prompt).ratio()
                self.assertLess(similarity, max_ratio)

    def test_mode_overrides_apply_per_mode(self):
        ai_settings = self.settings.get_runtime_settings()["ai"]

        mentor_profile = resolve_ai_profile(ai_settings, "mentor")
        free_talk_profile = resolve_ai_profile(ai_settings, "free_talk")
        dominant_profile = resolve_ai_profile(ai_settings, "dominant")

        self.assertEqual(mentor_profile["temperature"], 0.68)
        self.assertEqual(mentor_profile["max_completion_tokens"], 420)
        self.assertIn("структурировать мысль", mentor_profile["prompt_suffix"])

        self.assertEqual(free_talk_profile["temperature"], 0.95)
        self.assertEqual(free_talk_profile["max_completion_tokens"], 420)
        self.assertIn("живой взрослый человек", free_talk_profile["prompt_suffix"])

        self.assertEqual(dominant_profile["temperature"], 0.74)
        self.assertEqual(dominant_profile["max_completion_tokens"], 260)

    def test_comfort_mode_includes_ptsd_support_prompt(self):
        prompt = self._build_prompt("comfort")

        self.assertIn("В режиме поддержки при ПТСР", prompt)


if __name__ == "__main__":
    unittest.main()
