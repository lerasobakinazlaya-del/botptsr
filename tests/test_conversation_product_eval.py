import unittest
from pathlib import Path

from services.admin_settings_service import AdminSettingsService
from services.conversation_driver import build_followup, detect_intent
from services.conversation_engine_v2 import ConversationEngineV2


PRODUCT_HOOK_CASES = [
    "Что думаешь, запускать или нет?",
    "Брать этого человека в команду?",
    "Дожимать эту идею или выкинуть?",
    "Писать ему ещё раз или отпустить?",
    "Как тебе такой оффер?",
    "Слишком дорого или нормально?",
    "Стоит ли поднимать цену?",
    "Оставить эту фичу или резать?",
    "А если сделать всё проще?",
    "Почему это вообще не продаётся?",
    "Как тебе такой лендинг?",
    "Что тут цепляет, а что мертво?",
    "Сейчас пушить или подождать?",
    "Нормально звучит или слишком сухо?",
    "Переписывать с нуля или чинить?",
    "Это вообще жизнеспособно?",
    "Что скажешь про такой заход?",
    "Мне это нравится, но брать страшно",
    "Хочу сделать жёстче, стоит?",
    "Как тебе такой первый экран?",
    "Это выглядит дёшево или ок?",
    "Добавлять paywall так рано?",
    "Оставить этот тон или смягчить?",
    "Тут есть энергия или пусто?",
    "Что тут самое слабое место?",
    "Слишком рано просить деньги?",
    "Переходить на другой движок или нет?",
    "Мне дожимать эту тему дальше?",
]

VERBOSE_MODEL_STYLE = (
    "Это зависит от контекста. Сначала стоит внимательно посмотреть на риски, затем оценить ожидания, "
    "потом понять, насколько тебе это вообще подходит и какую цену ты за это заплатишь. "
    "Иногда лучше не спешить и разобрать всё по шагам, прежде чем принимать решение. "
    "В любом случае важно, чтобы решение было осознанным и не строилось на импульсе."
)

BANNED_FRAGMENTS = (
    "это зависит от контекста",
    "разобрать всё по шагам",
    "сначала стоит",
    "в любом случае важно",
)


class ConversationProductEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = AdminSettingsService(base_dir=Path(__file__).resolve().parents[1])
        cls.engine = ConversationEngineV2(settings)

    def test_product_hook_dataset_uses_short_dialogue_contract(self):
        for user_message in PRODUCT_HOOK_CASES:
            with self.subTest(user_message=user_message):
                prompt = self.engine.build_system_prompt(
                    state={"active_mode": "base", "emotional_tone": "neutral"},
                    access_level="analysis",
                    active_mode="base",
                    user_message=user_message,
                    history=[],
                )

                self.assertIn("short conversational probe", prompt)
                self.assertIn("Default to 2 compact sentences", prompt)
                self.assertIn("one sharp question", prompt)
                self.assertIn("not a request for an essay", prompt)

    def test_product_hook_dataset_guard_response_stays_short_and_substantive(self):
        for user_message in PRODUCT_HOOK_CASES:
            with self.subTest(user_message=user_message):
                result = self.engine.guard_response(
                    VERBOSE_MODEL_STYLE,
                    user_message=user_message,
                )
                lowered = result.lower()

                self.assertLessEqual(len(result), 320)
                self.assertLessEqual(result.count("?"), 1)
                self.assertLessEqual(len([part for part in result.replace("!", ".").replace("?", ".").split(".") if part.strip()]), 3)
                for fragment in BANNED_FRAGMENTS:
                    self.assertNotIn(fragment, lowered)

    def test_product_hook_dataset_has_meaningful_variation(self):
        outputs = [
            self.engine.guard_response(
                VERBOSE_MODEL_STYLE,
                user_message=user_message,
            )
            for user_message in PRODUCT_HOOK_CASES
        ]
        unique_outputs = set(outputs)

        self.assertGreaterEqual(len(unique_outputs), 11)

    def test_example_product_decision_flow_stays_dialogue_driven(self):
        followup = build_followup(
            detect_intent("Меня к этому тянет, но я ещё не решился"),
            {"conversation_phase": "warmup", "interaction_count": 4},
        )

        self.assertTrue(followup.endswith("?"))
        self.assertIn("или", followup)

    def test_example_interpersonal_emotional_flow_stays_dialogue_driven(self):
        followup = build_followup(
            detect_intent("Меня сильнее всего задел его тон"),
            {"conversation_phase": "warmup", "interaction_count": 6},
        )

        self.assertTrue(followup.endswith("?"))
        self.assertIn("или", followup)

    def test_example_confusion_flow_stays_dialogue_driven(self):
        followup = build_followup(
            detect_intent("Я не понимаю, зачем это вообще нужно"),
            {"conversation_phase": "start", "interaction_count": 1},
        )

        self.assertTrue(followup.endswith("?"))
        self.assertIn("или", followup)


if __name__ == "__main__":
    unittest.main()
