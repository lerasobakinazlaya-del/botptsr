import unittest

from services.response_guardrails import (
    analyze_response_style,
    apply_ptsd_response_guardrails,
    build_crisis_support_response,
    detect_crisis_signal,
)


class ResponseGuardrailsTests(unittest.TestCase):
    def test_guardrails_replace_canned_phrases_and_limit_questions(self):
        result = apply_ptsd_response_guardrails(
            "Я понимаю, что тебе тяжело. Твои чувства валидны. Что сейчас рядом? Чем помочь?",
            active_mode="free_talk",
            emotional_tone="anxious",
            enabled=True,
        )

        self.assertIn("слышу, как тебе тяжело", result.lower())
        self.assertIn("твоя реакция понятна", result.lower())
        self.assertEqual(result.count("?"), 1)

    def test_guardrails_do_not_change_other_modes(self):
        result = apply_ptsd_response_guardrails(
            "Я понимаю, что тебе тяжело. Что сейчас рядом?",
            active_mode="mentor",
            emotional_tone="anxious",
            enabled=True,
        )

        self.assertEqual(result, "Я понимаю, что тебе тяжело. Что сейчас рядом?")

    def test_analyze_response_style_reports_blocked_phrases(self):
        audit = analyze_response_style(
            "Я понимаю, что тебе тяжело. Давай побудем здесь.",
        )

        self.assertEqual(audit["question_count"], 0)
        self.assertEqual(audit["blocked_phrases"], ["я понимаю, что тебе тяжело"])
        self.assertFalse(audit["looks_overloaded"])

    def test_detect_crisis_signal_for_self_harm(self):
        crisis = detect_crisis_signal("Я не хочу жить и хочу покончить с собой.")

        self.assertEqual(crisis, "self_harm")

    def test_build_crisis_response_mentions_emergency_help(self):
        response = build_crisis_support_response("self_harm")

        self.assertIn("экстренные службы", response.lower())
        self.assertIn("не оставайся один", response.lower())


if __name__ == "__main__":
    unittest.main()
