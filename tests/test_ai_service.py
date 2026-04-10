import unittest

from services.ai_service import AIService


class FakeClient:
    def __init__(self, text: str):
        self.model = "gpt-4o-mini"
        self.temperature = 0.7
        self.text = text

    async def generate(self, **kwargs):
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
            return "Для начала важно", 42, "length"
        return "Для начала важно создать спокойный и естественный контакт.", 84, "stop"


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

    def build_reengagement_prompt(self, state, *, hours_silent, active_mode):
        return "Сформулируй одно живое сообщение первой инициативы."

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
            },
            "chat": {
                "response_guardrails_enabled": True,
                "response_guardrail_blocked_phrases": [
                    "я понимаю, что тебе тяжело",
                    "твои чувства валидны",
                ],
            },
            "engagement": {
                "adaptive_mode_enabled": True,
                "reengagement_recent_window_days": 30,
            },
        }


class AIServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_response_clamps_overloaded_ptsd_reply(self):
        prompt_builder = RecordingPromptBuilder()
        service = AIService(
            client=FakeLongReplyClient(
                "Я понимаю, что тебе тяжело. Твои чувства валидны. "
                "Сейчас попробуем разложить это на несколько частей. "
                "Сначала обрати внимание на дыхание. "
                "Потом осмотрись вокруг и назови пять предметов рядом. "
                "После этого прислушайся к телу и попробуй расслабить плечи. "
                "А затем напиши мне подробно, что происходит внутри? Чем помочь дальше?"
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
                user_message="Мне очень тревожно и трудно собраться.",
                state={
                    "active_mode": "free_talk",
                    "emotional_tone": "anxious",
                    "relationship_state": {},
                },
            )
        finally:
            await service.close()

        self.assertEqual(prompt_builder.calls[0]["active_mode"], "free_talk")
        self.assertIn("слышу, как тебе тяжело", result.response.lower())
        self.assertIn("твоя реакция понятна", result.response.lower())
        self.assertLessEqual(result.response.count("?"), 1)
        self.assertLessEqual(len(result.response), 340)
        self.assertEqual(result.new_state["last_assistant_source"], "reply")

    async def test_generate_reengagement_applies_response_guardrails(self):
        service = AIService(
            client=FakeClient(
                "Я понимаю, что тебе тяжело. Твои чувства валидны. Что рядом? Чем помочь?"
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
                "active_mode": "free_talk",
                "emotional_tone": "anxious",
                "relationship_state": {},
            },
        )

        lowered = result.response.lower()
        self.assertIn("слышу, как тебе тяжело", lowered)
        self.assertIn("твоя реакция понятна", lowered)
        self.assertEqual(result.response.count("?"), 1)

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
        )

        self.assertEqual(text, "Для начала важно создать спокойный и естественный контакт.")
        self.assertEqual(tokens_used, 84)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["max_completion_tokens"], 200)
        self.assertEqual(client.calls[1]["max_completion_tokens"], 400)
