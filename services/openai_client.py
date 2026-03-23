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
    ) -> Tuple[str, int | None]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )

        text = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None

        return text.strip(), tokens_used

    async def close(self) -> None:
        await self.client.close()
