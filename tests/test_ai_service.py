import unittest

from services.ai_service import AIBackpressureError, AIService


class FakeOpenAIClient:
    def get_runtime_stats(self):
        return {
            "configured_limit": 8,
            "in_flight_requests": 0,
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


if __name__ == "__main__":
    unittest.main()
