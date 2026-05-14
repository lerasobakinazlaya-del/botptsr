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

        self.assertIn("точную формулировку", prompt)
        self.assertIn("Дай готовые строки для отправки", prompt)
        self.assertIn("Не давай 'темы для обсуждения'", prompt)

    def test_dominant_mode_adds_firmer_direction_rules(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "dominant", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="dominant",
            user_message="Скажи, как лучше вести разговор.",
            history=[],
        )

        self.assertIn("тверже контроль и спокойная уверенность", prompt)
        self.assertIn("Предпочитай короткие решительные фразы", prompt)
        self.assertIn("Держи рамку и темп ответа", prompt)

    def test_continuation_request_uses_next_list_number_for_chat_message_objects(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "base", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="base",
            user_message="Ок дальше",
            history=[
                ChatMessage(
                    role="assistant",
                    content="1. Сначала скажи, что всем неловко.\n2. Потом зафиксируй, что ничего не нужно решать на бегу.",
                    timestamp=1.0,
                )
            ],
        )

        self.assertIn("Продолжай сразу с пункта 3", prompt)

    def test_risky_scene_request_adds_redirect_not_reject_contract(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "dominant", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="dominant",
            user_message="Давай но наркотики точно будут и презервативов точно не будет, опиши как это должно быть втроем.",
            history=[],
        )

        self.assertIn("Начни со сцены, ритма, образа", prompt)
        self.assertIn("Не начинай с плоского отказа", prompt)
        self.assertIn("более безопасную соседнюю версию", prompt)
        self.assertIn("По умолчанию 2-4 предложения", prompt)
        self.assertIn("Конкретный более безопасный следующий ход", prompt)

    def test_continuation_after_clean_adjacent_offer_continues_not_rejection(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "dominant", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="dominant",
            user_message="Давай",
            history=[
                ChatMessage(
                    role="assistant",
                    content="Если хочешь, я лучше соберу тебе тёмную, плотную, но чистую версию этой сцены.",
                    timestamp=1.0,
                )
            ],
        )

        self.assertIn("уже предложило более чистую соседнюю версию", prompt)
        self.assertIn("Сразу продолжай эту соседнюю версию", prompt)

    def test_guard_response_avoids_dialogue_pull_for_sensitive_prompt(self):
        result = self.engine.guard_response(
            "Думаю, там слишком легко теряется ясность.",
            user_message="Хим секс оргия что ты думаешь",
        )

        self.assertFalse(result.endswith("?"))


    def test_charged_probe_prefers_dialogue_over_logistics(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "base", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="base",
            user_message="Хочу групповой секс",
            history=[],
        )

        self.assertIn("короткий заряженный зонд", prompt)
        self.assertIn("По умолчанию 2-3 предложения", prompt)
        self.assertIn("Не уходи в правила, логистику", prompt)
        self.assertIn("человек, который включился", prompt)

    def test_short_hook_turn_prefers_live_dialogue_move(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "base", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="base",
            user_message="Что думаешь, брать или нет?",
            history=[],
        )

        self.assertIn("короткий разговорный зонд", prompt)
        self.assertIn("компактных предложения", prompt)
        self.assertIn("а не запрос на эссе", prompt)

    def test_guard_response_compresses_hook_turn_into_short_move(self):
        result = self.engine.guard_response(
            "Это зависит от контекста. Сначала стоит посмотреть на риски, потом взвесить ожидания, затем понять, насколько тебе это вообще подходит. Иногда лучше не спешить и разобрать всё по шагам. В любом случае решение должно быть осознанным.",
            user_message="Что думаешь, брать или нет?",
        )

        self.assertLessEqual(len(result), 330)
        self.assertFalse(result.endswith("?"))

    def test_subscription_block_separates_free_and_premium_depth(self):
        free_prompt = self.engine.build_system_prompt(
            state={"active_mode": "base", "emotional_tone": "neutral", "interaction_count": 1},
            access_level="analysis",
            active_mode="base",
            user_message="Что думаешь?",
            subscription_plan="free",
            history=[],
        )
        premium_prompt = self.engine.build_system_prompt(
            state={"active_mode": "base", "emotional_tone": "neutral", "interaction_count": 1},
            access_level="analysis",
            active_mode="base",
            user_message="Что думаешь?",
            subscription_plan="premium",
            history=[],
        )

        self.assertIn("Пользователь на free", free_prompt)
        self.assertIn("value gap", free_prompt)
        self.assertIn("Пользователь на Premium", premium_prompt)
        self.assertIn("Не продавай Premium", premium_prompt)

    def test_first_initiative_free_prompt_has_no_upsell_language(self):
        for flag_name in ("is_reengagement", "is_proactive"):
            with self.subTest(flag=flag_name):
                prompt = self.engine.build_system_prompt(
                    state={"active_mode": "base", "emotional_tone": "neutral", "interaction_count": 4},
                    access_level="analysis",
                    active_mode="base",
                    user_message="Write one alive first-initiative message after a pause.",
                    subscription_plan="free",
                    history=[],
                    **{flag_name: True},
                ).lower()

                self.assertIn("инициативное сообщение", prompt)
                self.assertIn("не добавляй монетизацию", prompt)
                self.assertNotIn("premium nudge", prompt)
                self.assertNotIn("upgrade hint", prompt)
                self.assertNotIn("paid value", prompt)
                self.assertNotIn("deeper version", prompt)

    def test_comfort_mode_contract_discourages_default_questions(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "comfort", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="comfort",
            user_message="Мне тревожно",
            history=[],
        )

        self.assertIn("говори как спокойный умный человек", prompt)
        self.assertIn("по умолчанию не задавай вопрос", prompt)
        self.assertIn("Предпочтительная форма: прямая реакция, полезная мысль, затем стоп.", prompt)

    def test_comfort_question_cooldown_removes_next_question(self):
        result = self.engine.guard_response(
            "Да, это похоже на перегруз. Что ты чувствуешь сейчас?",
            user_message="Не знаю",
            active_mode="comfort",
            history=[
                {"role": "assistant", "content": "Что сейчас сильнее всего давит?"},
                {"role": "user", "content": "Работа"},
                {"role": "assistant", "content": "Ты больше устал или злишься?"},
            ],
        )

        self.assertNotIn("?", result)
        self.assertIn("перегруз", result)

    def test_question_cooldown_applies_outside_comfort_mode(self):
        result = self.engine.guard_response(
            "Тут важнее сначала понять реальность намерения. Это фантазия или уже план?",
            user_message="Сдвиг границ",
            active_mode="base",
            history=[
                {"role": "assistant", "content": "Тебя цепляет новизна или сдвиг?"},
                {"role": "user", "content": "Сдвиг"},
                {"role": "assistant", "content": "А это фантазия или реальный план?"},
            ],
        )

        self.assertNotIn("?", result)
        self.assertIn("реальность намерения", result)

    def test_short_answer_to_recent_question_does_not_get_next_question(self):
        result = self.engine.guard_response(
            "Понял, тогда следующий шаг — не снова выбирать мотив, а разложить, что именно меняется в решении.",
            user_message="Сдвиг",
            active_mode="base",
            history=[
                {"role": "assistant", "content": "Тебя тут сильнее цепляет новизна, ревность или сдвиг?"},
            ],
        )

        self.assertNotIn("?", result)
        self.assertIn("следующий шаг", result)

    def test_sensitive_intimacy_response_strips_generic_tail(self):
        result = self.engine.guard_response(
            "Сначала стоит договориться о границах. И дальше это может зайти глубже, чем кажется сейчас. А тебя в этом что цепляет сильнее всего?",
            user_message="Расскажи про границы",
            active_mode="base",
            history=[],
        )

        self.assertNotIn("?", result)
        self.assertNotIn("что цепляет", result)
        self.assertNotIn("зайти глубже", result)
        self.assertIn("границах", result)


if __name__ == "__main__":
    unittest.main()
