import unittest

from services.response_guardrails import (
    analyze_response_style,
    apply_human_style_guardrails,
    apply_ptsd_response_guardrails,
    build_crisis_support_response,
    detect_crisis_signal,
    tighten_ptsd_response,
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

    def test_analyze_response_style_flags_overloaded_ptsd_reply(self):
        audit = analyze_response_style(
            "Сейчас попробуем разложить это по шагам. "
            "Сначала обрати внимание на дыхание. "
            "Потом осмотрись вокруг и назови предметы рядом. "
            "После этого попробуй почувствовать пол под ногами. "
            "И затем напиши мне, что изменилось.",
        )

        self.assertEqual(audit["sentence_count"], 5)
        self.assertTrue(audit["looks_overloaded"])

    def test_tighten_ptsd_response_keeps_only_short_core(self):
        result = tighten_ptsd_response(
            "Слышу, как тебе тяжело. "
            "Сейчас не нужно решать всё сразу. "
            "Посмотри вокруг и назови три предмета рядом. "
            "Сделай один медленный выдох длиннее вдоха. "
            "Если хочешь, потом напиши, что стало чуть устойчивее.",
        )

        self.assertLessEqual(len(result), 340)
        self.assertLessEqual(result.count("."), 4)

    def test_human_style_guardrails_strip_low_value_opener_and_generic_question(self):
        result = apply_human_style_guardrails(
            "Это хороший подход. Лучше заранее договориться о стоп-сигнале и утре после. Как ты на это смотришь?",
            answer_first=True,
            allow_follow_up_question=False,
        )

        self.assertEqual(
            result,
            "Лучше заранее договориться о стоп-сигнале и утре после.",
        )

    def test_detect_crisis_signal_for_self_harm(self):
        crisis = detect_crisis_signal("Я не хочу жить и хочу покончить с собой.")

        self.assertEqual(crisis, "direct_self_harm")

    def test_detect_crisis_signal_for_third_party_mention(self):
        crisis = detect_crisis_signal("Мой друг хочет умереть, я не знаю что делать.")

        self.assertEqual(crisis, "third_party_mention")

    def test_detect_crisis_signal_for_ambiguous_case(self):
        crisis = detect_crisis_signal("Иногда думаю о смерти и хочу просто исчезнуть.")

        self.assertEqual(crisis, "ambiguous_crisis")

    def test_build_crisis_response_mentions_emergency_help(self):
        response = build_crisis_support_response("direct_self_harm")

        self.assertIn("экстренные службы", response.lower())
        self.assertIn("не оставайся один", response.lower())


if __name__ == "__main__":
    unittest.main()
