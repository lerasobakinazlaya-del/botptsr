import asyncio
import logging
import time
from typing import Any, Dict, List, Tuple

from openai import AsyncOpenAI, BadRequestError


logger = logging.getLogger(__name__)


class OpenAIClient:
    MODEL_PRICING_USD_PER_1M_TOKENS = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
        "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
        "gpt-5-mini": {"input": 0.25, "output": 2.00},
    }

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.9,
        max_parallel_requests: int | None = None,
        usage_repository=None,
    ):
        if not api_key:
            raise ValueError("OpenAI API key is required")

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_parallel_requests = max_parallel_requests or 0
        self.usage_repository = usage_repository
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
        usage_context: dict[str, Any] | None = None,
    ) -> Tuple[str, int | None]:
        payload = self._build_payload(
            messages=messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            user=user,
        )

        response, latency_ms = await self._run_with_limits(payload)

        text = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None
        await self._record_usage_event(
            response=response,
            latency_ms=latency_ms,
            finish_reason=getattr(response.choices[0], "finish_reason", None),
            model_name=str(payload.get("model") or self.model),
            request_user=user,
            usage_context=usage_context,
        )

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
        usage_context: dict[str, Any] | None = None,
    ) -> Tuple[str, int | None, str | None]:
        payload = self._build_payload(
            messages=messages,
            model=model,
            temperature=temperature,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            user=user,
        )

        response, latency_ms = await self._run_with_limits(payload)

        choice = response.choices[0]
        text = choice.message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else None
        finish_reason = getattr(choice, "finish_reason", None)
        await self._record_usage_event(
            response=response,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            model_name=str(payload.get("model") or self.model),
            request_user=user,
            usage_context=usage_context,
        )

        return text.strip(), tokens_used, finish_reason

    def _build_payload(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str | None,
        temperature: float | None,
        top_p: float | None,
        frequency_penalty: float | None,
        presence_penalty: float | None,
        max_completion_tokens: int | None,
        reasoning_effort: str | None,
        verbosity: str | None,
        user: str | None,
    ) -> Dict[str, Any]:
        model_name = model or self.model
        payload = {
            "model": model_name,
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
        if reasoning_effort and self._supports_reasoning_effort(model_name):
            payload["reasoning_effort"] = reasoning_effort
        if verbosity and self._supports_verbosity(model_name):
            payload["verbosity"] = verbosity
        if user:
            payload["user"] = user
        return payload

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
            response = await self._create_completion_with_fallback(payload)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            return response, latency_ms
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

    async def _record_usage_event(
        self,
        *,
        response,
        latency_ms: float,
        finish_reason: str | None,
        model_name: str,
        request_user: str | None,
        usage_context: dict[str, Any] | None,
    ) -> None:
        if self.usage_repository is None:
            return

        usage = getattr(response, "usage", None)
        if usage is None:
            return

        metadata = dict(usage_context or {})
        user_id = metadata.pop("user_id", None)
        source = str(metadata.pop("source", "")).strip() or "unknown"
        if request_user:
            metadata["request_user"] = request_user

        try:
            await self.usage_repository.log_event(
                user_id=int(user_id) if user_id not in (None, "") else None,
                source=source,
                model=model_name,
                prompt_tokens=self._usage_value(usage, "prompt_tokens"),
                completion_tokens=self._usage_value(usage, "completion_tokens"),
                total_tokens=self._usage_value(usage, "total_tokens"),
                reasoning_tokens=self._nested_usage_value(usage, "completion_tokens_details", "reasoning_tokens"),
                cached_tokens=self._nested_usage_value(usage, "prompt_tokens_details", "cached_tokens"),
                estimated_cost_usd=self._estimate_cost_usd(
                    model_name=model_name,
                    prompt_tokens=self._usage_value(usage, "prompt_tokens"),
                    completion_tokens=self._usage_value(usage, "completion_tokens"),
                ),
                latency_ms=latency_ms,
                finish_reason=finish_reason,
                request_user=request_user,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("Failed to record OpenAI usage event: %s", exc)

    @classmethod
    def _estimate_cost_usd(
        cls,
        *,
        model_name: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> float | None:
        pricing = cls.MODEL_PRICING_USD_PER_1M_TOKENS.get(str(model_name or "").strip().lower())
        if pricing is None:
            return None
        return round(
            ((max(0, int(prompt_tokens or 0)) / 1_000_000.0) * float(pricing["input"]))
            + ((max(0, int(completion_tokens or 0)) / 1_000_000.0) * float(pricing["output"])),
            6,
        )

    @staticmethod
    def _usage_value(usage: Any, field: str) -> int | None:
        value = getattr(usage, field, None)
        if value in (None, ""):
            return None
        return int(value)

    @staticmethod
    def _nested_usage_value(usage: Any, field: str, nested_field: str) -> int | None:
        payload = getattr(usage, field, None)
        if payload is None:
            return None
        value = getattr(payload, nested_field, None)
        if value in (None, ""):
            return None
        return int(value)

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

    def _supports_reasoning_effort(self, model_name: str) -> bool:
        normalized = str(model_name or "").strip().lower()
        return normalized.startswith("gpt-5")

    def _supports_verbosity(self, model_name: str) -> bool:
        normalized = str(model_name or "").strip().lower()
        return normalized.startswith("gpt-5")

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
