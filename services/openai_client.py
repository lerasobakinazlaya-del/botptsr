import asyncio
import logging
import time
from typing import Any, Dict, List, Tuple

from openai import AsyncOpenAI, BadRequestError


logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.9,
        max_parallel_requests: int | None = None,
    ):
        if not api_key:
            raise ValueError("OpenAI API key is required")

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_parallel_requests = max_parallel_requests or 0
        self._semaphore = (
            asyncio.Semaphore(self.max_parallel_requests)
            if self.max_parallel_requests > 0
            else None
        )
        self._in_flight_requests = 0
        self._waiting_requests = 0
        self._total_requests = 0
        self._failed_requests = 0
        self._last_wait_ms = 0.0
        self._max_wait_ms = 0.0
        self._last_latency_ms = 0.0
        self._max_latency_ms = 0.0

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

        response = await self._run_with_limits(payload)

        text = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None

        return text.strip(), tokens_used

    async def generate_with_meta(
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
    ) -> Tuple[str, int | None, str | None]:
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

        response = await self._run_with_limits(payload)

        choice = response.choices[0]
        text = choice.message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None
        finish_reason = getattr(choice, "finish_reason", None)

        return text.strip(), tokens_used, finish_reason

    def get_runtime_stats(self) -> Dict[str, int | float]:
        return {
            "configured_limit": self.max_parallel_requests,
            "in_flight_requests": self._in_flight_requests,
            "waiting_requests": self._waiting_requests,
            "total_requests": self._total_requests,
            "failed_requests": self._failed_requests,
            "last_wait_ms": self._last_wait_ms,
            "max_wait_ms": self._max_wait_ms,
            "last_latency_ms": self._last_latency_ms,
            "max_latency_ms": self._max_latency_ms,
        }

    async def _run_with_limits(self, payload: Dict[str, Any]):
        wait_started = time.perf_counter()
        acquired = False
        self._waiting_requests += 1

        try:
            if self._semaphore is not None:
                await self._semaphore.acquire()
                acquired = True
        finally:
            wait_ms = round((time.perf_counter() - wait_started) * 1000, 1)
            self._last_wait_ms = wait_ms
            self._max_wait_ms = max(self._max_wait_ms, wait_ms)
            self._waiting_requests = max(0, self._waiting_requests - 1)

        started = time.perf_counter()
        self._in_flight_requests += 1
        self._total_requests += 1

        try:
            return await self._create_completion_with_fallback(payload)
        except Exception:
            self._failed_requests += 1
            raise
        finally:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            self._last_latency_ms = latency_ms
            self._max_latency_ms = max(self._max_latency_ms, latency_ms)
            self._in_flight_requests = max(0, self._in_flight_requests - 1)
            if acquired and self._semaphore is not None:
                self._semaphore.release()

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

        if "temperature" in error_text:
            changed = self._relax_temperature(payload, error_text=error_text) or changed

        if "top_p" in error_text:
            changed = self._relax_numeric_option(
                payload,
                key="top_p",
                fallback=1.0,
                error_text=error_text,
            ) or changed

        if "frequency_penalty" in error_text:
            changed = self._relax_numeric_option(
                payload,
                key="frequency_penalty",
                fallback=0.0,
                error_text=error_text,
            ) or changed

        if "presence_penalty" in error_text:
            changed = self._relax_numeric_option(
                payload,
                key="presence_penalty",
                fallback=0.0,
                error_text=error_text,
            ) or changed

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

    def _relax_temperature(
        self,
        payload: Dict[str, Any],
        *,
        error_text: str,
    ) -> bool:
        if "temperature" not in payload:
            return False

        if "default (1)" in error_text or "default value (1)" in error_text:
            if payload.get("temperature") != 1:
                payload["temperature"] = 1
                return True
            return False

        payload.pop("temperature", None)
        return True

    def _relax_numeric_option(
        self,
        payload: Dict[str, Any],
        *,
        key: str,
        fallback: float,
        error_text: str,
    ) -> bool:
        if key not in payload:
            return False

        if "default" in error_text:
            if payload.get(key) != fallback:
                payload[key] = fallback
                return True
            return False

        payload.pop(key, None)
        return True

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
