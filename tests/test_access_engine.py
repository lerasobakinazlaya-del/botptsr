import unittest

from services.access_engine import AccessEngine


class AccessEngineSafetyTests(unittest.TestCase):
    def setUp(self):
        self.engine = AccessEngine()

    def test_intimate_access_is_downgraded_without_explicit_signal(self):
        result = self.engine.apply_safety_guardrails(
            state={"emotional_tone": "neutral"},
            access_level="rare_layer",
            active_mode="passion",
            user_message="Спасибо, с тобой спокойно.",
        )

        self.assertEqual(result, "analysis")

    def test_intimate_access_is_allowed_with_explicit_signal(self):
        result = self.engine.apply_safety_guardrails(
            state={"emotional_tone": "warm"},
            access_level="personal_focus",
            active_mode="passion",
            user_message="Флиртуй со мной и будь ближе.",
        )

        self.assertEqual(result, "personal_focus")

    def test_heavy_state_blocks_intimate_access_even_with_signal(self):
        result = self.engine.apply_safety_guardrails(
            state={"emotional_tone": "anxious"},
            access_level="tension",
            active_mode="night",
            user_message="Хочу, чтобы ты была ближе.",
        )

        self.assertEqual(result, "analysis")

    def test_non_intimate_mode_never_escalates_above_analysis(self):
        result = self.engine.apply_safety_guardrails(
            state={"emotional_tone": "warm"},
            access_level="analysis",
            active_mode="free_talk",
            user_message="Флиртуй со мной и будь ближе.",
        )

        self.assertEqual(result, "analysis")


if __name__ == "__main__":
    unittest.main()
