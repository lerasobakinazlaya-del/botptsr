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

    def test_dominant_mode_adds_firmer_direction_rules(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "dominant", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="dominant",
            user_message="Скажи, как лучше вести разговор.",
            history=[],
        )

        self.assertIn("firmer control and calm authority", prompt)
        self.assertIn("Prefer shorter decisive sentences over soft hedging.", prompt)
        self.assertIn("Hold the frame and tempo of the reply", prompt)

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

    def test_risky_scene_request_adds_redirect_not_reject_contract(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "night", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="night",
            user_message="Давай но наркотики точно будут и презервативов точно не будет, опиши как это должно быть втроем.",
            history=[],
        )

        self.assertIn("Start with scene, rhythm, image, tension, or dynamics", prompt)
        self.assertIn("Do not open with a flat rejection", prompt)
        self.assertIn("redirect toward a safer adjacent version", prompt)
        self.assertIn("Default to 2-4 sentences", prompt)
        self.assertIn("Prefer ending with one sharp follow-up question", prompt)

    def test_continuation_after_clean_adjacent_offer_continues_not_rejection(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "night", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="night",
            user_message="Давай",
            history=[
                ChatMessage(
                    role="assistant",
                    content="Если хочешь, я лучше соберу тебе тёмную, плотную, но чистую версию этой сцены.",
                    timestamp=1.0,
                )
            ],
        )

        self.assertIn("already offered a cleaner adjacent version", prompt)
        self.assertIn("Continue with that adjacent version immediately", prompt)

    def test_guard_response_adds_dialogue_pull_for_charged_prompt(self):
        result = self.engine.guard_response(
            "Думаю, там слишком легко теряется ясность.",
            user_message="Хим секс оргия что ты думаешь",
        )

        self.assertTrue(result.endswith("?"))


    def test_charged_probe_prefers_dialogue_over_logistics(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "free_talk", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="free_talk",
            user_message="Хочу групповой секс",
            history=[],
        )

        self.assertIn("short charged probe or conversation opener", prompt)
        self.assertIn("Default to 2 compact sentences", prompt)
        self.assertIn("Do not pivot into rules, logistics, negotiation, or risk management", prompt)
        self.assertIn("feel like a person leaning in", prompt)

    def test_short_hook_turn_prefers_live_dialogue_move(self):
        prompt = self.engine.build_system_prompt(
            state={"active_mode": "free_talk", "emotional_tone": "neutral"},
            access_level="analysis",
            active_mode="free_talk",
            user_message="Что думаешь, брать или нет?",
            history=[],
        )

        self.assertIn("short conversational probe", prompt)
        self.assertIn("Default to 2 compact sentences", prompt)
        self.assertIn("not a request for an essay", prompt)

    def test_guard_response_compresses_hook_turn_into_short_move(self):
        result = self.engine.guard_response(
            "Это зависит от контекста. Сначала стоит посмотреть на риски, потом взвесить ожидания, затем понять, насколько тебе это вообще подходит. Иногда лучше не спешить и разобрать всё по шагам. В любом случае решение должно быть осознанным.",
            user_message="Что думаешь, брать или нет?",
        )

        self.assertLessEqual(len(result), 330)
        self.assertTrue(result.endswith("?"))


if __name__ == "__main__":
    unittest.main()
