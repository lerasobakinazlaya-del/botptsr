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
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class FakeResponse:
    def __init__(self, content, total_tokens=42, finish_reason="stop"):
        self.choices = [FakeChoice(content, finish_reason=finish_reason)]
        self.usage = FakeUsage(total_tokens)


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
    async def test_generate_retries_with_medium_verbosity_when_low_is_rejected(self):
        client = OpenAIClient(api_key="test-key")
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
        client = OpenAIClient(api_key="test-key")
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
