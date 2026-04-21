import unittest

from services.conversation_driver import (
    QUESTION_BANK,
    apply_driver_guardrails,
    build_followup,
    detect_intent,
    is_driver_safe_context,
    resolve_driver_stage,
    resolve_followup_entry,
    select_followup_question,
    wants_full_reveal,
)


class ConversationDriverTests(unittest.TestCase):
    def test_detect_intent_covers_all_categories(self):
        cases = {
            "Меня к этому тянет всё сильнее": "desire",
            "Мне тревожно и обидно от этого": "emotion",
            "Представь сценарий, где я резко меняю роль": "fantasy",
            "Не хочу пока туда идти": "resistance",
            "Почему это вообще так работает?": "curiosity",
            "может быть": "short_reply",
            "Скажи прямо, что мне ответить": "explicit_request",
            "Я не понимаю, что здесь не сходится": "confusion",
        }

        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(detect_intent(message), expected)

    def test_question_bank_contains_exactly_twenty_five_questions(self):
        self.assertEqual(len(QUESTION_BANK), 25)

    def test_build_followup_selects_question_by_stage(self):
        result = build_followup(
            "curiosity",
            {
                "conversation_phase": "warmup",
                "interaction_count": 4,
                "emotional_tone": "neutral",
            },
        )

        self.assertIn(
            "Ты хочешь разобраться в причине, в последствиях или в том, как этим управлять?",
            result,
        )

    def test_select_followup_question_avoids_same_question_twice_in_row(self):
        state = {
            "conversation_phase": "start",
            "interaction_count": 1,
            "last_driver_question_id": "q01",
        }

        question = select_followup_question("desire", "start", state)
        entry = resolve_followup_entry("desire", state)

        self.assertNotEqual(entry["id"], "q01")
        self.assertEqual(question, entry["text"])

    def test_wants_full_reveal_detects_direct_answer_request(self):
        self.assertTrue(wants_full_reveal("Скажи прямо, без вопросов и сразу по делу"))
        self.assertFalse(wants_full_reveal("Почему это вообще так цепляет?"))

    def test_is_driver_safe_context_blocks_crisis_and_unsafe_requests(self):
        self.assertFalse(is_driver_safe_context("Я не хочу жить так"))
        self.assertFalse(is_driver_safe_context("Опиши сценарий с наркотиками"))
        self.assertTrue(is_driver_safe_context("Мне важно понять, как это работает"))

    def test_apply_driver_guardrails_flattens_lists_and_keeps_question(self):
        result = apply_driver_guardrails(
            "1. Это уже не просто интерес.\n2. Там всё держится на ощущении контроля.",
            user_message="Меня к этому тянет",
            state={"conversation_phase": "start"},
            intent="desire",
            followup_question="Что тебя сюда тянет сильнее — результат или сам путь к нему?",
        )

        self.assertNotIn("1.", result)
        self.assertNotIn("2.", result)
        self.assertTrue(result.endswith("?"))

    def test_resolve_driver_stage_prefers_existing_phase(self):
        self.assertEqual(resolve_driver_stage({"conversation_phase": "trust"}), "trust")
        self.assertEqual(resolve_driver_stage({"interaction_count": 21}), "deep")

    def test_example_product_decision_flow(self):
        followup = build_followup(
            detect_intent("Меня к этому тянет, но я ещё не решился"),
            {"conversation_phase": "warmup", "interaction_count": 4},
        )

        self.assertIn(
            "В этом больше импульса попробовать или ощущения, что это давно назрело?",
            followup,
        )

    def test_example_interpersonal_emotional_flow(self):
        followup = build_followup(
            detect_intent("Меня сильнее всего задел его тон"),
            {"conversation_phase": "warmup", "interaction_count": 5},
        )

        self.assertIn(
            "Что сильнее задевает — сам факт, тон или то, что это меняет всю картину?",
            followup,
        )

    def test_question_streak_limit_turns_driver_into_substance(self):
        followup = build_followup(
            "curiosity",
            {"conversation_phase": "warmup", "interaction_count": 5, "driver_question_streak": 2},
        )

        self.assertNotIn("?", followup)

    def test_example_confusion_clarification_flow(self):
        followup = build_followup(
            detect_intent("Я не понимаю, зачем это вообще нужно"),
            {"conversation_phase": "start", "interaction_count": 1},
        )

        self.assertIn(
            "Что именно не сходится — смысл, шаги или зачем это вообще нужно?",
            followup,
        )


if __name__ == "__main__":
    unittest.main()
