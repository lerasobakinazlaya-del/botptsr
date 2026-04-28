import unittest

from services.ai_service import AIService
from services.memory_engine import ChatMessage


class FakeClient:
    def __init__(self, text: str):
        self.model = "gpt-4o-mini"
        self.temperature = 0.7
        self.text = text
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.text, 42


class FakeLongReplyClient(FakeClient):
    pass


class FakeTruncatingClient:
    def __init__(self):
        self.model = "gpt-4o-mini"
        self.temperature = 0.7
        self.calls = []

    async def generate_with_meta(self, **kwargs):
        self.calls.append(dict(kwargs))
        if len(self.calls) == 1:
            return "\u0420\u201d\u0420\u00bb\u0421\u040f \u0420\u0405\u0420\u00b0\u0421\u2021\u0420\u00b0\u0420\u00bb\u0420\u00b0 \u0420\u0406\u0420\u00b0\u0420\u00b6\u0420\u0405\u0420\u0455", 42, "length"
        return "\u0420\u201d\u0420\u00bb\u0421\u040f \u0420\u0405\u0420\u00b0\u0421\u2021\u0420\u00b0\u0420\u00bb\u0420\u00b0 \u0420\u0406\u0420\u00b0\u0420\u00b6\u0420\u0405\u0420\u0455 \u0421\u0403\u0420\u0455\u0420\u00b7\u0420\u0491\u0420\u00b0\u0421\u201a\u0421\u040a \u0421\u0403\u0420\u0457\u0420\u0455\u0420\u0454\u0420\u0455\u0420\u2116\u0420\u0405\u0421\u2039\u0420\u2116 \u0420\u0451 \u0420\u00b5\u0421\u0403\u0421\u201a\u0420\u00b5\u0421\u0403\u0421\u201a\u0420\u0406\u0420\u00b5\u0420\u0405\u0420\u0405\u0421\u2039\u0420\u2116 \u0420\u0454\u0420\u0455\u0420\u0405\u0421\u201a\u0420\u00b0\u0420\u0454\u0421\u201a.", 84, "stop"


class FakeStateEngine:
    def update_state(self, state, user_message):
        return dict(state)


class FakeMemoryEngine:
    def set_max_tokens(self, max_tokens):
        self.max_tokens = max_tokens

    async def build_context(self, history, max_tokens=None):
        return []


class FakeKeywordMemoryService:
    def apply(self, state, user_message):
        return dict(state)

    def detect_grounding_need(self, text):
        return None

    def build_grounding_response(self, kind):
        return ""

    def build_prompt_context(self, state, history=None):
        return ""


class FakeLongTermMemoryService:
    async def build_prompt_context(self, user_id):
        return ""


class FakeMemoryProfileService:
    def __init__(self, text=""):
        self.text = text
        self.calls = []

    async def build_prompt_context(self, *, user_id, state, history=None):
        self.calls.append(
            {
                "user_id": user_id,
                "state": dict(state),
                "history_len": len(history or []),
            }
        )
        return self.text


class FakeHumanMemoryService:
    def apply_user_message(self, state, user_message):
        return dict(state)

    def apply_assistant_message(self, state, assistant_text, *, source="reply"):
        updated = dict(state)
        updated["last_assistant_text"] = assistant_text
        updated["last_assistant_source"] = source
        return updated

    def hours_since_iso(self, value, fallback=24):
        return fallback

    def build_reengagement_prompt(self, state, *, hours_silent, active_mode, style_settings=None):
        return "\u0420\u040e\u0421\u201e\u0420\u0455\u0421\u0402\u0420\u0458\u0421\u0453\u0420\u00bb\u0420\u0451\u0421\u0402\u0421\u0453\u0420\u2116 \u0420\u0455\u0420\u0491\u0420\u0405\u0420\u0455 \u0420\u00b6\u0420\u0451\u0420\u0406\u0420\u0455\u0420\u00b5 \u0421\u0403\u0420\u0455\u0420\u0455\u0420\u00b1\u0421\u2030\u0420\u00b5\u0420\u0405\u0420\u0451\u0420\u00b5 \u0420\u0457\u0420\u00b5\u0421\u0402\u0420\u0406\u0420\u0455\u0420\u2116 \u0420\u0451\u0420\u0405\u0420\u0451\u0421\u2020\u0420\u0451\u0420\u00b0\u0421\u201a\u0420\u0451\u0420\u0406\u0421\u2039."

    def suggest_mode(self, state, current_mode):
        return current_mode

    def build_prompt_context(self, state):
        return ""

    def get_reengagement_context(self, state):
        return {"topic": "", "callback_hint": ""}

    def mark_reengagement_callback(self, state, callback_topic):
        updated = dict(state)
        updated["last_callback_topic"] = callback_topic or ""
        return updated


class FakePromptBuilder:
    def build_system_prompt(self, **kwargs):
        return "system prompt"


class RecordingPromptBuilder(FakePromptBuilder):
    def __init__(self):
        self.calls = []

    def build_system_prompt(self, **kwargs):
        self.calls.append(dict(kwargs))
        return "system prompt"


class FakeAccessEngine:
    def update_access_level(self, state):
        return "analysis"

    def evaluate_access(self, *, state, access_level, active_mode, user_message, is_proactive=False):
        return {"level": access_level, "clamped": False}


class FakeSettingsService:
    def get_runtime_settings(self):
        return {
            "ai": {
                "openai_model": "gpt-4o-mini",
                "temperature": 0.8,
                "top_p": 1.0,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0,
                "max_completion_tokens": 200,
                "timeout_seconds": 5,
                "max_retries": 0,
                "memory_max_tokens": 800,
                "history_message_limit": 10,
                "response_language": "ru",
                "mode_overrides": {},
                "verbosity": "medium",
                "reasoning_effort": "",
                "dialogue": {
                    "hook_max_sentences": 2,
                    "hook_max_chars": 260,
                    "hook_require_follow_up_question": False,
                    "hook_topic_questions_enabled": False,
                    "risky_scene_compact_redirect": True,
                    "charged_probe_compact_redirect": True,
                },
                "fast_lane": {
                    "enabled": True,
                    "hook_max_completion_tokens": 110,
                    "continuation_max_completion_tokens": 140,
                    "scene_max_completion_tokens": 180,
                    "generic_max_completion_tokens": 200,
                    "hook_memory_max_tokens": 450,
                    "continuation_memory_max_tokens": 700,
                    "scene_memory_max_tokens": 800,
                    "generic_memory_max_tokens": 900,
                    "hook_history_message_limit": 5,
                    "continuation_history_message_limit": 8,
                    "scene_history_message_limit": 9,
                    "generic_history_message_limit": 10,
                    "hook_timeout_seconds": 8,
                    "continuation_timeout_seconds": 10,
                    "scene_timeout_seconds": 12,
                    "generic_timeout_seconds": 12,
                    "hook_max_retries": 0,
                    "continuation_max_retries": 0,
                    "scene_max_retries": 1,
                    "generic_max_retries": 1,
                    "force_low_verbosity": True,
                    "force_low_reasoning": True,
                },
            },
            "chat": {
                "response_guardrails_enabled": True,
                "response_guardrail_blocked_phrases": [
                    "\u044f \u043f\u043e\u043d\u0438\u043c\u0430\u044e, \u0447\u0442\u043e \u0442\u0435\u0431\u0435 \u0442\u044f\u0436\u0435\u043b\u043e",
                    "\u0442\u0432\u043e\u0438 \u0447\u0443\u0432\u0441\u0442\u0432\u0430 \u0432\u0430\u043b\u0438\u0434\u043d\u044b",
                ],
            },
            "engagement": {
                "adaptive_mode_enabled": True,
                "reengagement_recent_window_days": 30,
                "reengagement_style": {
                    "enabled_families": [
                        "soft_presence",
                        "callback_thread",
                        "mood_ping",
                        "playful_hook",
                    ],
                    "prefer_callback_thread": False,
                    "allow_question": False,
                    "max_chars": 220,
                    "max_completion_tokens": 120,
                },
            },
        }


class ConversationDriverFlagSettingsService(FakeSettingsService):
    def __init__(self, enabled):
        self.enabled = enabled

    def get_runtime_settings(self):
        settings = super().get_runtime_settings()
        settings["engagement"]["conversation_driver_enabled"] = self.enabled
        return settings


class AIServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_lane_profile_shrinks_short_hook_turns(self):
        service = AIService(
            client=FakeClient("ok"),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )

        optimized = service._apply_fast_lane_profile(
            {
                "max_completion_tokens": 220,
                "memory_max_tokens": 1000,
                "history_message_limit": 12,
                "timeout_seconds": 20,
                "max_retries": 2,
            },
            user_message="\u0420\u00a7\u0421\u201a\u0420\u0455 \u0420\u0491\u0421\u0453\u0420\u0458\u0420\u00b0\u0420\u00b5\u0421\u20ac\u0421\u040a, \u0420\u00b1\u0421\u0402\u0420\u00b0\u0421\u201a\u0421\u040a \u0420\u0451\u0420\u00bb\u0420\u0451 \u0420\u0405\u0420\u00b5\u0421\u201a?",
            active_mode="base",
        )

        self.assertEqual(optimized["max_completion_tokens"], 110)
        self.assertEqual(optimized["memory_max_tokens"], 450)
        self.assertEqual(optimized["history_message_limit"], 5)
        self.assertEqual(optimized["timeout_seconds"], 8)
        self.assertEqual(optimized["max_retries"], 0)

    async def test_build_memory_context_prefers_unified_memory_profile_service(self):
        memory_profile_service = FakeMemoryProfileService("- \u0420\u2019\u0420\u00b0\u0420\u00b6\u0420\u0405\u0421\u2039\u0420\u00b5 \u0420\u0451\u0420\u0458\u0420\u00b5\u0420\u0405\u0420\u00b0 \u0420\u0451 \u0421\u0403\u0420\u0406\u0421\u040f\u0420\u00b7\u0420\u0451: \u0420\u0457\u0420\u0455\u0420\u00bb\u0421\u040a\u0420\u00b7\u0420\u0455\u0420\u0406\u0420\u00b0\u0421\u201a\u0420\u00b5\u0420\u00bb\u0421\u040f \u0420\u00b7\u0420\u0455\u0420\u0406\u0421\u0453\u0421\u201a \u0420\u203a\u0420\u00b5\u0420\u0405\u0420\u00b0")
        service = AIService(
            client=FakeClient("ok"),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
            memory_profile_service=memory_profile_service,
        )

        context = await service._build_memory_context(
            {"user_profile": {}, "memory_flags": {}, "relationship_state": {}},
            user_id=1,
            history=[],
        )

        self.assertEqual(context, "- \u0420\u2019\u0420\u00b0\u0420\u00b6\u0420\u0405\u0421\u2039\u0420\u00b5 \u0420\u0451\u0420\u0458\u0420\u00b5\u0420\u0405\u0420\u00b0 \u0420\u0451 \u0421\u0403\u0420\u0406\u0421\u040f\u0420\u00b7\u0420\u0451: \u0420\u0457\u0420\u0455\u0420\u00bb\u0421\u040a\u0420\u00b7\u0420\u0455\u0420\u0406\u0420\u00b0\u0421\u201a\u0420\u00b5\u0420\u00bb\u0421\u040f \u0420\u00b7\u0420\u0455\u0420\u0406\u0421\u0453\u0421\u201a \u0420\u203a\u0420\u00b5\u0420\u0405\u0420\u00b0")
        self.assertEqual(len(memory_profile_service.calls), 1)

    async def test_generate_response_strips_robotic_opener_and_generic_question(self):
        prompt_builder = RecordingPromptBuilder()
        service = AIService(
            client=FakeClient(
                "\u042d\u0442\u043e \u0445\u043e\u0440\u043e\u0448\u0438\u0439 \u043f\u043e\u0434\u0445\u043e\u0434. "
                "\u041b\u0443\u0447\u0448\u0435 \u0437\u0430\u0440\u0430\u043d\u0435\u0435 \u0434\u043e\u0433\u043e\u0432\u043e\u0440\u0438\u0442\u044c\u0441\u044f \u043e \u0441\u0442\u043e\u043f-\u0441\u0438\u0433\u043d\u0430\u043b\u0435 \u0438 \u0443\u0442\u0440\u0435 \u043f\u043e\u0441\u043b\u0435. "
                "\u041a\u0430\u043a \u0442\u044b \u043d\u0430 \u044d\u0442\u043e \u0441\u043c\u043e\u0442\u0440\u0438\u0448\u044c?"
            ),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=prompt_builder,
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="\u0421\u043e\u0441\u0442\u0430\u0432\u044c \u043f\u043b\u0430\u043d, \u043a\u0430\u043a \u043b\u0443\u0447\u0448\u0435 \u0432\u0441\u0435 \u043e\u0431\u0441\u0443\u0434\u0438\u0442\u044c \u0437\u0430\u0440\u0430\u043d\u0435\u0435.",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        self.assertEqual(
            result.response,
            "\u041b\u0443\u0447\u0448\u0435 \u0437\u0430\u0440\u0430\u043d\u0435\u0435 \u0434\u043e\u0433\u043e\u0432\u043e\u0440\u0438\u0442\u044c\u0441\u044f \u043e \u0441\u0442\u043e\u043f-\u0441\u0438\u0433\u043d\u0430\u043b\u0435 \u0438 \u0443\u0442\u0440\u0435 \u043f\u043e\u0441\u043b\u0435.",
        )
    async def test_generate_response_adds_emotional_hook_for_conversational_turn(self):
        service = AIService(
            client=FakeClient("\u0420\u0407 \u0420\u00b1\u0421\u2039 \u0420\u0405\u0420\u00b5 \u0421\u201a\u0420\u0455\u0421\u0402\u0420\u0455\u0420\u0457\u0420\u0451\u0420\u00bb\u0421\u0403\u0421\u040f \u0421\u0403 \u0421\u040c\u0421\u201a\u0420\u0451\u0420\u0458."),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="\u0420\u0459\u0420\u00b0\u0420\u0454 \u0421\u201a\u0420\u00b5\u0420\u00b1\u0420\u00b5 \u0421\u201a\u0420\u00b0\u0420\u0454\u0420\u0455\u0420\u2116 \u0421\u2026\u0420\u0455\u0420\u0491?",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "conversation_phase": "warmup",
                    "interaction_count": 4,
                    "interest": 0.64,
                    "attraction": 0.22,
                    "control": 0.51,
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        self.assertNotEqual(result.response, "\u0420\u0407 \u0420\u00b1\u0421\u2039 \u0420\u0405\u0420\u00b5 \u0421\u201a\u0420\u0455\u0421\u0402\u0420\u0455\u0420\u0457\u0420\u0451\u0420\u00bb\u0421\u0403\u0421\u040f \u0421\u0403 \u0421\u040c\u0421\u201a\u0420\u0451\u0420\u0458.")
        self.assertIn(result.new_state["last_hook"], result.response)
        self.assertTrue(
            result.response.endswith("?") or "\u0420\u0405\u0420\u00b5 \u0420\u0406\u0421\u0403\u0421\u040f \u0420\u0454\u0420\u00b0\u0421\u0402\u0421\u201a\u0420\u0451\u0420\u0405\u0420\u00b0" in result.response.lower()
        )

    async def test_generate_response_injects_conversation_driver_into_prompt(self):
        client = FakeClient("Тут явно есть сдвиг.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="Меня к этому тянет",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("Conversation driver override:", system_prompt)
        self.assertIn("Use this as a steering hint", system_prompt)
        self.assertIn("detected intent: desire", system_prompt)
        self.assertIn("selected question id: q01", system_prompt)
        self.assertIn("possible follow-up question", system_prompt)
        self.assertIn("Max 3 sentences.", system_prompt)
        self.assertEqual(result.new_state["last_detected_intent"], "desire")
        self.assertEqual(result.new_state["last_driver_question_id"], "q01")
        self.assertEqual(result.new_state["driver_question_streak"], 1)

    async def test_free_plan_first_messages_get_soft_premium_nudge_contract(self):
        client = FakeClient("Коротко: да. В Premium я бы разобрал это глубже и без обрыва на полуслове.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="Ок",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "interaction_count": 1,
                    "relationship_state": {},
                },
                subscription_plan="free",
            )
        finally:
            await service.close()

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("User is free", system_prompt)
        self.assertIn("Early conversation: make the value gap visible", system_prompt)
        self.assertIn("natural continuation of this exact conversation", system_prompt)
        self.assertIn("premium", result.response.lower())
        self.assertNotIn("buy premium", result.response.lower())
        self.assertNotIn("upgrade now", result.response.lower())
        self.assertLessEqual(result.response.count("?"), 1)
    async def test_generate_response_flattens_list_style_when_driver_is_active(self):
        service = AIService(
            client=FakeClient(
                "1. item one.\n"
                "2. item two."
            ),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="\u0420\u045a\u0420\u00b5\u0420\u0405\u0421\u040f \u0421\u040c\u0421\u201a\u0420\u0455 \u0421\u2020\u0420\u00b5\u0420\u0457\u0420\u00bb\u0421\u040f\u0420\u00b5\u0421\u201a",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        self.assertNotIn("1.", result.response)
        self.assertNotIn("2.", result.response)
        self.assertIn("?", result.response)

    async def test_generate_response_skips_driver_for_full_reveal_request(self):
        client = FakeClient("Скажу прямо и без обходов.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="Скажи прямо, без вопросов и сразу по делу",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertNotIn("Conversation driver override:", system_prompt)
        self.assertNotIn("last_driver_question_id", result.new_state)
    async def test_generate_response_skips_driver_for_crisis_signal(self):
        client = FakeClient("\u0421\u0435\u0439\u0447\u0430\u0441 \u0432\u0430\u0436\u043d\u043e \u0443\u0434\u0435\u0440\u0436\u0430\u0442\u044c\u0441\u044f \u0437\u0430 \u043e\u043f\u043e\u0440\u0443.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="\u042f \u043d\u0435 \u0445\u043e\u0447\u0443 \u0436\u0438\u0442\u044c \u0442\u0430\u043a",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        self.assertEqual(client.calls, [])
        self.assertNotIn("last_driver_question_id", result.new_state)
    async def test_generate_response_respects_explicit_driver_flag(self):
        client = FakeClient("\u0420\u045e\u0421\u0453\u0421\u201a \u0421\u040f\u0420\u0406\u0420\u0405\u0420\u0455 \u0420\u00b5\u0421\u0403\u0421\u201a\u0421\u040a \u0421\u0403\u0420\u0491\u0420\u0406\u0420\u0451\u0420\u0456.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=ConversationDriverFlagSettingsService(False),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="\u0420\u045f\u0420\u0455\u0421\u2021\u0420\u00b5\u0420\u0458\u0421\u0453 \u0421\u040c\u0421\u201a\u0420\u0455 \u0420\u0406\u0420\u0455\u0420\u0455\u0420\u00b1\u0421\u2030\u0420\u00b5 \u0421\u2020\u0420\u00b5\u0420\u0457\u0420\u00bb\u0421\u040f\u0420\u00b5\u0421\u201a?",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertNotIn("Conversation driver override:", system_prompt)
        self.assertNotIn("last_driver_question_id", result.new_state)
    async def test_generate_response_adds_list_continuation_instruction(self):
        client = FakeClient("2. \u041e\u0431\u0441\u0443\u0434\u0438\u0442\u0435 \u0437\u0430\u0440\u0430\u043d\u0435\u0435 \u0441\u0442\u043e\u043f-\u0441\u0438\u0433\u043d\u0430\u043b \u0438 \u043a\u0442\u043e \u0441\u043b\u0435\u0434\u0438\u0442 \u0437\u0430 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435\u043c.\n3. \u0423\u0442\u0440\u043e\u043c \u043d\u0435 \u0441\u043f\u0435\u0448\u0438\u0442\u0435, \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435, \u0432\u0441\u0435\u043c \u043b\u0438 \u043e\u043a.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=RecordingPromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            await service.generate_response(
                user_id=1,
                history=[
                    {
                        "role": "assistant",
                        "content": "\u0412\u043e\u0442 \u043f\u0440\u0438\u043c\u0435\u0440\u043d\u044b\u0439 \u043f\u043b\u0430\u043d:\n1. \u0417\u0430\u0440\u0430\u043d\u0435\u0435 \u043e\u0431\u0441\u0443\u0434\u0438\u0442\u0435 \u0433\u0440\u0430\u043d\u0438\u0446\u044b \u0438 \u0447\u0442\u043e \u0442\u043e\u0447\u043d\u043e \u043e\u043a \u0434\u043b\u044f \u0432\u0441\u0435\u0445.",
                    }
                ],
                user_message="Ок далее",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("Continue directly from item 2", system_prompt)
        self.assertIn("instead of restarting", system_prompt)
        self.assertEqual(client.calls[0]["max_completion_tokens"], 140)
        self.assertEqual(client.calls[0]["verbosity"], "low")
        self.assertEqual(client.calls[0]["reasoning_effort"], "low")
    async def test_generate_response_adds_harm_reduction_instruction_for_sex_and_drugs(self):
        client = FakeClient("Нужно заранее обсудить границы, трезвого наблюдателя и утро после.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=RecordingPromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            await service.generate_response(
                user_id=1,
                history=[],
                user_message="Составь план на групповой секс под мефом и 2cb",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("Do not romanticize altered-state scenarios with blurred control.", system_prompt)
        self.assertIn("Do not provide step-by-step use, mixing, or escalation instructions.", system_prompt)
        self.assertIn("Stay on harm reduction", system_prompt)
    async def test_generate_response_allows_single_question_when_user_requests_it(self):
        client = FakeClient("Ок, давай так и сделаем.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=RecordingPromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            await service.generate_response(
                user_id=1,
                history=[],
                user_message="Можешь спрашивать и вести разговор сама",
                state={
                    "active_mode": "base",
                    "emotional_tone": "neutral",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        system_prompt = client.calls[0]["messages"][0]["content"]
        self.assertIn("The user explicitly invited questions.", system_prompt)
    async def test_generate_response_clamps_overloaded_ptsd_reply(self):
        prompt_builder = RecordingPromptBuilder()
        service = AIService(
            client=FakeLongReplyClient(
                "\u042f \u043f\u043e\u043d\u0438\u043c\u0430\u044e, \u0447\u0442\u043e \u0442\u0435\u0431\u0435 \u0442\u044f\u0436\u0435\u043b\u043e. \u0422\u0432\u043e\u0438 \u0447\u0443\u0432\u0441\u0442\u0432\u0430 \u0432\u0430\u043b\u0438\u0434\u043d\u044b. "
                "\u0421\u0435\u0439\u0447\u0430\u0441 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0435\u043c \u0440\u0430\u0437\u043b\u043e\u0436\u0438\u0442\u044c \u044d\u0442\u043e \u043d\u0430 \u043d\u0435\u0441\u043a\u043e\u043b\u044c\u043a\u043e \u0447\u0430\u0441\u0442\u0435\u0439. "
                "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043e\u0431\u0440\u0430\u0442\u0438 \u0432\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u043d\u0430 \u0434\u044b\u0445\u0430\u043d\u0438\u0435. "
                "\u041f\u043e\u0442\u043e\u043c \u043e\u0441\u043c\u043e\u0442\u0440\u0438\u0441\u044c \u0432\u043e\u043a\u0440\u0443\u0433 \u0438 \u043d\u0430\u0437\u043e\u0432\u0438 \u043f\u044f\u0442\u044c \u043f\u0440\u0435\u0434\u043c\u0435\u0442\u043e\u0432 \u0440\u044f\u0434\u043e\u043c. "
                "\u041f\u043e\u0441\u043b\u0435 \u044d\u0442\u043e\u0433\u043e \u043f\u0440\u0438\u0441\u043b\u0443\u0448\u0430\u0439\u0441\u044f \u043a \u0442\u0435\u043b\u0443 \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0440\u0430\u0441\u0441\u043b\u0430\u0431\u0438\u0442\u044c \u043f\u043b\u0435\u0447\u0438. "
                "\u0410 \u0437\u0430\u0442\u0435\u043c \u043d\u0430\u043f\u0438\u0448\u0438 \u043c\u043d\u0435 \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u043e, \u0447\u0442\u043e \u043f\u0440\u043e\u0438\u0441\u0445\u043e\u0434\u0438\u0442 \u0432\u043d\u0443\u0442\u0440\u0438? \u0427\u0435\u043c \u043f\u043e\u043c\u043e\u0447\u044c \u0434\u0430\u043b\u044c\u0448\u0435?"
            ),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=prompt_builder,
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )
        await service.start()
        try:
            result = await service.generate_response(
                user_id=1,
                history=[],
                user_message="\u041c\u043d\u0435 \u043e\u0447\u0435\u043d\u044c \u0442\u0440\u0435\u0432\u043e\u0436\u043d\u043e \u0438 \u0442\u0440\u0443\u0434\u043d\u043e \u0441\u043e\u0431\u0440\u0430\u0442\u044c\u0441\u044f.",
                state={
                    "active_mode": "comfort",
                    "emotional_tone": "anxious",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        self.assertIn("\u0441\u043b\u044b\u0448\u0443, \u043a\u0430\u043a \u0442\u0435\u0431\u0435 \u0442\u044f\u0436\u0435\u043b\u043e", result.response.lower())
        self.assertIn("\u0442\u0432\u043e\u044f \u0440\u0435\u0430\u043a\u0446\u0438\u044f \u043f\u043e\u043d\u044f\u0442\u043d\u0430", result.response.lower())
        self.assertLessEqual(result.response.count("?"), 1)
        self.assertLessEqual(len(result.response), 340)
        self.assertEqual(result.new_state["last_assistant_source"], "reply")
    async def test_generate_reengagement_applies_response_guardrails(self):
        service = AIService(
            client=FakeClient(
                "\u042f \u043f\u043e\u043d\u0438\u043c\u0430\u044e, \u0447\u0442\u043e \u0442\u0435\u0431\u0435 \u0442\u044f\u0436\u0435\u043b\u043e. \u0422\u0432\u043e\u0438 \u0447\u0443\u0432\u0441\u0442\u0432\u0430 \u0432\u0430\u043b\u0438\u0434\u043d\u044b. \u0427\u0442\u043e \u0440\u044f\u0434\u043e\u043c? \u0427\u0435\u043c \u043f\u043e\u043c\u043e\u0447\u044c?"
            ),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )

        result = await service.generate_reengagement(
            user_id=1,
            history=[],
            state={
                "active_mode": "comfort",
                "emotional_tone": "anxious",
                "relationship_state": {},
            },
        )

        lowered = result.response.lower()
        self.assertIn("\u0441\u043b\u044b\u0448\u0443, \u043a\u0430\u043a \u0442\u0435\u0431\u0435 \u0442\u044f\u0436\u0435\u043b\u043e", lowered)
        self.assertIn("\u0442\u0432\u043e\u044f \u0440\u0435\u0430\u043a\u0446\u0438\u044f \u043f\u043e\u043d\u044f\u0442\u043d\u0430", lowered)
        self.assertEqual(result.response.count("?"), 1)
    async def test_generate_reengagement_uses_fast_short_profile(self):
        client = FakeClient("\u0420\u045f\u0421\u0402\u0420\u0451\u0420\u0406\u0420\u00b5\u0421\u201a. \u0420\u0407 \u0420\u0406\u0420\u0491\u0421\u0402\u0421\u0453\u0420\u0456 \u0420\u0455 \u0421\u201a\u0420\u00b5\u0420\u00b1\u0420\u00b5 \u0420\u0406\u0421\u0403\u0420\u0457\u0420\u0455\u0420\u0458\u0420\u0405\u0420\u0451\u0420\u00bb\u0420\u00b0.")
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )

        await service.generate_reengagement(
            user_id=1,
            history=[],
            state={
                "active_mode": "base",
                "emotional_tone": "neutral",
                "relationship_state": {},
            },
        )

        self.assertEqual(client.calls[0]["max_completion_tokens"], 120)
        self.assertEqual(client.calls[0]["verbosity"], "low")
        self.assertEqual(client.calls[0]["reasoning_effort"], "low")

    async def test_call_with_retry_retries_once_when_response_was_truncated(self):
        client = FakeTruncatingClient()
        service = AIService(
            client=client,
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )

        text, tokens_used = await service._call_with_retry(
            [{"role": "user", "content": "hi"}],
            ai_settings=FakeSettingsService().get_runtime_settings()["ai"],
            ai_profile={
                "model": "gpt-4o-mini",
                "temperature": 0.8,
                "max_completion_tokens": 200,
                "timeout_seconds": 5,
                "max_retries": 0,
            },
            user_id=1,
            usage_source="chat",
        )

        self.assertEqual(text, "\u0420\u201d\u0420\u00bb\u0421\u040f \u0420\u0405\u0420\u00b0\u0421\u2021\u0420\u00b0\u0420\u00bb\u0420\u00b0 \u0420\u0406\u0420\u00b0\u0420\u00b6\u0420\u0405\u0420\u0455 \u0421\u0403\u0420\u0455\u0420\u00b7\u0420\u0491\u0420\u00b0\u0421\u201a\u0421\u040a \u0421\u0403\u0420\u0457\u0420\u0455\u0420\u0454\u0420\u0455\u0420\u2116\u0420\u0405\u0421\u2039\u0420\u2116 \u0420\u0451 \u0420\u00b5\u0421\u0403\u0421\u201a\u0420\u00b5\u0421\u0403\u0421\u201a\u0420\u0406\u0420\u00b5\u0420\u0405\u0420\u0405\u0421\u2039\u0420\u2116 \u0420\u0454\u0420\u0455\u0420\u0405\u0421\u201a\u0420\u00b0\u0420\u0454\u0421\u201a.")
        self.assertEqual(tokens_used, 84)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["max_completion_tokens"], 200)
        self.assertEqual(client.calls[1]["max_completion_tokens"], 400)

    def test_assistant_question_heavy_supports_chat_message_objects(self):
        service = AIService(
            client=FakeClient("ok"),
            state_engine=FakeStateEngine(),
            memory_engine=FakeMemoryEngine(),
            keyword_memory_service=FakeKeywordMemoryService(),
            long_term_memory_service=FakeLongTermMemoryService(),
            human_memory_service=FakeHumanMemoryService(),
            prompt_builder=FakePromptBuilder(),
            access_engine=FakeAccessEngine(),
            settings_service=FakeSettingsService(),
        )

        history = [
            ChatMessage(role="assistant", content="\u0420\u0459\u0420\u00b0\u0420\u0454 \u0421\u201a\u0421\u2039 \u0420\u0405\u0420\u00b0 \u0421\u040c\u0421\u201a\u0420\u0455 \u0421\u0403\u0420\u0458\u0420\u0455\u0421\u201a\u0421\u0402\u0420\u0451\u0421\u20ac\u0421\u040a?", timestamp=1.0),
            ChatMessage(role="assistant", content="\u0420\u00a7\u0421\u201a\u0420\u0455 \u0420\u0491\u0421\u0453\u0420\u0458\u0420\u00b0\u0420\u00b5\u0421\u20ac\u0421\u040a \u0420\u0491\u0420\u00b0\u0420\u00bb\u0421\u040a\u0421\u20ac\u0420\u00b5?", timestamp=2.0),
        ]

        self.assertTrue(service._assistant_has_been_question_heavy(history))
