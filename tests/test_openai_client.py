import unittest

import httpx
from openai import BadRequestError

from services.openai_client import OpenAIClient


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeUsage:
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class FakeResponse:
    def __init__(self, content, total_tokens=42):
        self.choices = [FakeChoice(content)]
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
