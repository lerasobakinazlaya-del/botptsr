import unittest

from services.ai_service import AIBackpressureError, AIService


class FakeOpenAIClient:
    def __init__(self):
        self.called = False

    def get_runtime_stats(self):
        return {
            "configured_limit": 8,
            "in_flight_requests": 0,
        }

    async def generate(self, **kwargs):
        self.called = True
        return ("ok", 10)


class FakeStateEngine:
    def update_state(self, state, user_message):
        updated = dict(state)
        updated.setdefault("active_mode", "base")
        updated.setdefault("emotional_tone", "neutral")
        return updated


class FakeMemoryEngine:
    async def build_context(self, history, *, max_tokens=None):
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
        return updated

    def suggest_mode(self, state, active_mode):
        return active_mode

    def build_prompt_context(self, state):
        return ""

    def build_reengagement_prompt(self, state, *, hours_silent, active_mode):
        return ""

    def get_reengagement_context(self, state):
        return {"topic": "", "callback_hint": ""}

    def mark_reengagement_callback(self, state, callback_topic):
        updated = dict(state)
        if callback_topic:
            updated["callback_topic"] = callback_topic
        return updated


class FakePromptBuilder:
    def build_system_prompt(self, **kwargs):
        return "system"


class FakeAccessEngine:
    def update_access_level(self, state):
        return "analysis"

    def evaluate_access(self, **kwargs):
        return {
            "level": "analysis",
            "clamped": False,
            "reason": "",
        }

    def apply_safety_guardrails(self, **kwargs):
        return "analysis"


class FakeSettingsService:
    def get_runtime_settings(self):
        return {
            "ai": {
                "openai_model": "gpt-4o-mini",
                "temperature": 0.9,
                "top_p": 1.0,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0,
                "max_completion_tokens": 300,
                "reasoning_effort": "",
                "verbosity": "medium",
                "memory_max_tokens": 500,
                "mode_overrides": {},
            },
            "chat": {
                "response_guardrails_enabled": True,
                "response_guardrail_blocked_phrases": [],
            },
            "engagement": {
                "adaptive_mode_enabled": False,
                "reengagement_recent_window_days": 30,
            },
        }


class AIServiceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_response_times_out_while_waiting_for_worker(self):
        service = AIService(
            client=FakeOpenAIClient(),
            state_engine=None,
            memory_engine=None,
            keyword_memory_service=None,
            long_term_memory_service=None,
            human_memory_service=None,
            prompt_builder=None,
            access_engine=None,
            settings_service=None,
            queue_wait_timeout_seconds=0.01,
        )
        service._started = True  # type: ignore[attr-defined]

        with self.assertRaises(AIBackpressureError):
            await service.generate_response(
                user_id=1,
                history=[],
                user_message="hi",
                state={},
            )

        stats = service.get_runtime_stats()
        self.assertEqual(stats["requests_queue_timed_out"], 1)
        self.assertEqual(stats["openai_configured_limit"], 8)
        self.assertEqual(stats["crisis_bypass_count"], 0)

    async def test_generate_response_returns_crisis_bypass_without_model_call(self):
        client = FakeOpenAIClient()
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

        result = await service._generate_response_impl(
            history=[],
            user_message="Я не хочу жить и хочу покончить с собой.",
            state={},
            user_id=1,
        )

        self.assertFalse(client.called)
        self.assertIn("экстренные службы", result.response.lower())
        self.assertIn("не оставайся один", result.response.lower())
        self.assertEqual(service.get_runtime_stats()["crisis_bypass_count"], 1)


if __name__ == "__main__":
    unittest.main()
