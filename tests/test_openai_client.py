import asyncio
import unittest

import httpx
from openai import BadRequestError

from services.openai_client import OpenAIClient


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = FakeMessage(content)
        self.finish_reason = finish_reason


class FakeUsage:
    def __init__(self, total_tokens, prompt_tokens=30, completion_tokens=12):
        self.total_tokens = total_tokens
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeResponse:
    def __init__(self, content, total_tokens=42, finish_reason="stop", prompt_tokens=30, completion_tokens=12):
        self.choices = [FakeChoice(content, finish_reason=finish_reason)]
        self.usage = FakeUsage(total_tokens, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


class FakeUsageRepository:
    def __init__(self):
        self.events = []

    async def log_event(self, **payload):
        self.events.append(dict(payload))


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.payloads = []

    async def create(self, **payload):
        self.payloads.append(dict(payload))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeChat:
    def __init__(self, outcomes):
        self.completions = FakeCompletions(outcomes)


class FakeAsyncOpenAI:
    def __init__(self, outcomes):
        self.chat = FakeChat(outcomes)

    async def close(self):
        return None


def make_bad_request(message: str) -> BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError(message, response=response, body={})


class OpenAIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_skips_unsupported_verbosity_and_reasoning_for_gpt_4o_mini(self):
        client = OpenAIClient(api_key="test-key")
        fake_client = FakeAsyncOpenAI([FakeResponse("ok")])
        client.client = fake_client

        text, tokens = await client.generate(
            messages=[{"role": "user", "content": "hi"}],
            verbosity="low",
            reasoning_effort="high",
        )

        self.assertEqual(text, "ok")
        self.assertEqual(tokens, 42)
        self.assertNotIn("verbosity", fake_client.chat.completions.payloads[0])
        self.assertNotIn("reasoning_effort", fake_client.chat.completions.payloads[0])

    async def test_generate_retries_with_medium_verbosity_when_low_is_rejected(self):
        client = OpenAIClient(api_key="test-key", model="gpt-5")
        fake_client = FakeAsyncOpenAI(
            [
                make_bad_request(
                    "Unsupported value: 'verbosity' does not support 'low' with this model. Supported values are: 'medium'."
                ),
                FakeResponse("ok"),
            ]
        )
        client.client = fake_client

        text, tokens = await client.generate(
            messages=[{"role": "user", "content": "hi"}],
            verbosity="low",
        )

        self.assertEqual(text, "ok")
        self.assertEqual(tokens, 42)
        self.assertEqual(fake_client.chat.completions.payloads[0]["verbosity"], "low")
        self.assertEqual(fake_client.chat.completions.payloads[1]["verbosity"], "medium")

    async def test_generate_drops_unknown_reasoning_effort_and_retries(self):
        client = OpenAIClient(api_key="test-key", model="gpt-5")
        fake_client = FakeAsyncOpenAI(
            [
                make_bad_request("Unknown parameter: 'reasoning_effort'."),
                FakeResponse("done"),
            ]
        )
        client.client = fake_client

        text, _tokens = await client.generate(
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="high",
        )

        self.assertEqual(text, "done")
        self.assertIn("reasoning_effort", fake_client.chat.completions.payloads[0])
        self.assertNotIn("reasoning_effort", fake_client.chat.completions.payloads[1])

    async def test_generate_tracks_global_openai_waiters(self):
        class SlowCompletions:
            def __init__(self):
                self.payloads = []

            async def create(self, **payload):
                self.payloads.append(dict(payload))
                await asyncio.sleep(0.05)
                return FakeResponse("ok")

        class SlowChat:
            def __init__(self):
                self.completions = SlowCompletions()

        class SlowAsyncOpenAI:
            def __init__(self):
                self.chat = SlowChat()

            async def close(self):
                return None

        client = OpenAIClient(api_key="test-key", max_parallel_requests=1)
        client.client = SlowAsyncOpenAI()

        first = asyncio.create_task(client.generate(messages=[{"role": "user", "content": "one"}]))
        await asyncio.sleep(0.01)
        second = asyncio.create_task(client.generate(messages=[{"role": "user", "content": "two"}]))
        await asyncio.sleep(0.01)

        stats_while_running = client.get_runtime_stats()
        self.assertEqual(stats_while_running["in_flight_requests"], 1)
        self.assertEqual(stats_while_running["waiting_requests"], 1)

        await asyncio.gather(first, second)

        final_stats = client.get_runtime_stats()
        self.assertEqual(final_stats["total_requests"], 2)
        self.assertGreater(final_stats["max_wait_ms"], 0)

    async def test_generate_with_meta_returns_finish_reason(self):
        client = OpenAIClient(api_key="test-key")
        fake_client = FakeAsyncOpenAI([FakeResponse("partial", finish_reason="length")])
        client.client = fake_client

        text, tokens, finish_reason = await client.generate_with_meta(
            messages=[{"role": "user", "content": "hi"}],
        )

        self.assertEqual(text, "partial")
        self.assertEqual(tokens, 42)
        self.assertEqual(finish_reason, "length")

    async def test_generate_retries_with_default_temperature_when_model_rejects_custom_value(self):
        client = OpenAIClient(api_key="test-key")
        fake_client = FakeAsyncOpenAI(
            [
                make_bad_request(
                    "Unsupported value: 'temperature' does not support 0.2 with this model. Only the default (1) value is supported."
                ),
                FakeResponse("ok"),
            ]
        )
        client.client = fake_client

        text, tokens = await client.generate(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
        )

        self.assertEqual(text, "ok")
        self.assertEqual(tokens, 42)
        self.assertEqual(fake_client.chat.completions.payloads[0]["temperature"], 0.2)
        self.assertEqual(fake_client.chat.completions.payloads[1]["temperature"], 1)

    async def test_generate_retries_with_default_sampling_penalties_when_model_rejects_them(self):
        client = OpenAIClient(api_key="test-key")
        fake_client = FakeAsyncOpenAI(
            [
                make_bad_request(
                    "Unsupported value: 'frequency_penalty' with this model. Only the default value is supported."
                ),
                make_bad_request(
                    "Unsupported value: 'presence_penalty' with this model. Only the default value is supported."
                ),
                FakeResponse("ok"),
            ]
        )
        client.client = fake_client

        text, tokens = await client.generate(
            messages=[{"role": "user", "content": "hi"}],
            frequency_penalty=0.2,
            presence_penalty=0.1,
        )

        self.assertEqual(text, "ok")
        self.assertEqual(tokens, 42)
        self.assertEqual(fake_client.chat.completions.payloads[1]["frequency_penalty"], 0.0)
        self.assertEqual(fake_client.chat.completions.payloads[2]["presence_penalty"], 0.0)

    async def test_generate_records_usage_event_with_source_and_cost_estimate(self):
        usage_repository = FakeUsageRepository()
        client = OpenAIClient(api_key="test-key", usage_repository=usage_repository)
        client.client = FakeAsyncOpenAI([FakeResponse("ok", total_tokens=42, prompt_tokens=30, completion_tokens=12)])

        text, tokens = await client.generate(
            messages=[{"role": "user", "content": "hi"}],
            user="123:chat",
            usage_context={"source": "chat", "user_id": 123, "entrypoint": "telegram"},
        )

        self.assertEqual(text, "ok")
        self.assertEqual(tokens, 42)
        self.assertEqual(len(usage_repository.events), 1)
        event = usage_repository.events[0]
        self.assertEqual(event["source"], "chat")
        self.assertEqual(event["user_id"], 123)
        self.assertEqual(event["prompt_tokens"], 30)
        self.assertEqual(event["completion_tokens"], 12)
        self.assertEqual(event["total_tokens"], 42)
        self.assertEqual(event["request_user"], "123:chat")
        self.assertEqual(event["metadata"]["entrypoint"], "telegram")
        self.assertGreater(event["estimated_cost_usd"], 0.0)
