import unittest

from services.ai_service import AIService


class FakeClient:
    def __init__(self, text: str):
        self.model = "gpt-4o-mini"
        self.temperature = 0.7
        self.text = text

    async def generate(self, **kwargs):
        return self.text, 42


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
