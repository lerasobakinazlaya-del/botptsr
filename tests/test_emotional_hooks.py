import unittest

from services.emotional_hooks import ensure_open_loop, inject_hook, select_hook


class EmotionalHooksTests(unittest.TestCase):
    def test_select_hook_uses_curiosity_in_early_stage(self):
        hook = select_hook(
            {
                "conversation_phase": "start",
                "interaction_count": 1,
                "interest": 0.25,
                "attraction": 0.08,
                "control": 0.9,
            },
            "auto",
        )

        self.assertTrue(hook)
        self.assertIn(
            hook,
            {
                "и здесь есть деталь, которую обычно замечают не сразу",
                "но самое интересное тут чуть глубже",
                "и именно это обычно меняет весь тон дальше",
                "но тут все решает один тихий нюанс",
                "и в этом месте картина только начинает раскрываться",
                "но главное здесь не лежит на поверхности",
            },
        )

    def test_select_hook_avoids_repeating_last_hook(self):
        state = {
            "conversation_phase": "deep",
            "interaction_count": 28,
            "interest": 0.66,
            "attraction": 0.41,
            "control": 0.31,
            "last_hook": "и это только точка, где все начинает набирать силу",
        }

        hook = select_hook(state, "auto")

        self.assertNotEqual(hook, state["last_hook"])

    def test_select_hook_prefers_personalization_for_high_engagement(self):
        hook = select_hook(
            {
                "conversation_phase": "trust",
                "interaction_count": 11,
                "interest": 0.84,
                "attraction": 0.44,
                "control": 0.38,
            },
            "auto",
        )

        self.assertIn("тво", hook.lower())

    def test_inject_hook_blends_into_existing_sentence(self):
        result = inject_hook(
            "Я бы не спешил с этим.",
            "но тут все решает один тихий нюанс",
        )

        self.assertEqual(
            result,
            "Я бы не спешил с этим, но тут все решает один тихий нюанс.",
        )

    def test_ensure_open_loop_adds_open_ending(self):
        result = ensure_open_loop("Я бы не спешил с этим.")

        self.assertIn("Если хочешь, продолжим.", result)
        self.assertTrue(result.endswith("."))


if __name__ == "__main__":
    unittest.main()
