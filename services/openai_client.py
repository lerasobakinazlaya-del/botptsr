import logging
from typing import Any, Dict, List, Tuple

from openai import AsyncOpenAI, BadRequestError


logger = logging.getLogger(__name__)


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

        response = await self._create_completion_with_fallback(payload)

        text = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None

        return text.strip(), tokens_used

    async def _create_completion_with_fallback(self, payload: Dict[str, Any]):
        request_payload = dict(payload)

        while True:
            try:
                return await self.client.chat.completions.create(**request_payload)
            except BadRequestError as exc:
                if not self._relax_unsupported_request_options(request_payload, exc):
                    raise

    def _relax_unsupported_request_options(
        self,
        payload: Dict[str, Any],
        exc: BadRequestError,
    ) -> bool:
        error_text = str(exc).lower()
        changed = False

        if "verbosity" in error_text:
            changed = self._relax_named_option(
                payload,
                key="verbosity",
                error_text=error_text,
            ) or changed

        if "reasoning_effort" in error_text:
            changed = self._relax_named_option(
                payload,
                key="reasoning_effort",
                error_text=error_text,
            ) or changed

        if changed:
            logger.warning(
                "Retrying OpenAI request with relaxed options after bad request: %s",
                str(exc),
            )
        return changed

    def _relax_named_option(
        self,
        payload: Dict[str, Any],
        *,
        key: str,
        error_text: str,
    ) -> bool:
        if key not in payload:
            return False

        current_value = str(payload.get(key) or "").strip().lower()
        if "supported values" in error_text and current_value and current_value != "medium":
            payload[key] = "medium"
            return True

        payload.pop(key, None)
        return True

    async def close(self) -> None:
        await self.client.close()
