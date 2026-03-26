from typing import Dict, List, Tuple

from openai import AsyncOpenAI


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.9,
    ):
        if not api_key:
            raise ValueError("OpenAI API key is required")

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        max_completion_tokens: int | None = None,
        reasoning_effort: str | None = None,
        verbosity: str | None = None,
        user: str | None = None,
    ) -> Tuple[str, int | None]:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
        }
        if top_p is not None:
            payload["top_p"] = top_p
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            payload["presence_penalty"] = presence_penalty
        if max_completion_tokens is not None:
            payload["max_completion_tokens"] = max_completion_tokens
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if verbosity:
            payload["verbosity"] = verbosity
        if user:
            payload["user"] = user

        response = await self.client.chat.completions.create(**payload)

        text = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None

        return text.strip(), tokens_used

    async def close(self) -> None:
        await self.client.close()
