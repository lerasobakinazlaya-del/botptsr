import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from services.ai_profile_service import resolve_ai_profile
from services.prompt_safety import redact_prompt_for_log
from services.response_guardrails import (
    analyze_response_style,
    apply_ptsd_response_guardrails,
    build_crisis_support_response,
    detect_crisis_signal,
    tighten_ptsd_response,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIResult:
    response: str
    new_state: Dict[str, Any]
    tokens_used: int | None = None


@dataclass
class AIRequest:
    user_id: int
    history: List[Dict[str, str]]
    user_message: str
    state: Dict[str, Any]
    future: asyncio.Future
    started_event: asyncio.Event
    enqueued_at: float


class AIBackpressureError(RuntimeError):
    pass


class AIService:
    EMPTY_RESPONSE_FALLBACK = (
        "Я рядом. Попробуй написать это чуть иначе, и я отвечу точнее."
    )
    MAX_TRUNCATION_RETRIES = 1
    TRUNCATION_TOKEN_MULTIPLIER = 2
    MAX_TRUNCATION_COMPLETION_TOKENS = 1200

    def __init__(
        self,
        client,
        state_engine,
        memory_engine,
        keyword_memory_service,
        long_term_memory_service,
        human_memory_service,
        prompt_builder,
        access_engine,
        settings_service,
        debug: bool = False,
        log_full_prompt: bool = False,
        debug_prompt_user_id: int | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 2,
        max_parallel_requests: int = 4,
        queue_size: int = 100,
        queue_wait_timeout_seconds: int = 25,
    ):
        self.client = client
        self.state_engine = state_engine
        self.memory_engine = memory_engine
        self.keyword_memory_service = keyword_memory_service
        self.long_term_memory_service = long_term_memory_service
        self.human_memory_service = human_memory_service
        self.prompt_builder = prompt_builder
        self.access_engine = access_engine
        self.settings_service = settings_service
        self.debug = debug
        self.log_full_prompt = log_full_prompt
        self.debug_prompt_user_id = debug_prompt_user_id

        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_parallel_requests = max_parallel_requests
        self.queue_wait_timeout_seconds = queue_wait_timeout_seconds

        self._queue: asyncio.Queue[AIRequest | None] = asyncio.Queue(maxsize=queue_size)
        self._workers: list[asyncio.Task] = []
        self._started = False
        self._busy_workers = 0
        self._requests_started = 0
        self._requests_completed = 0
        self._requests_failed = 0
        self._requests_rejected = 0
        self._requests_queue_timed_out = 0
        self._last_queue_wait_ms = 0.0
        self._max_queue_wait_ms = 0.0
        self._last_run_ms = 0.0
        self._max_run_ms = 0.0
        self._crisis_bypass_count = 0
        self._intimacy_clamp_count = 0
        self._reengagement_clamped_count = 0

    async def start(self) -> None:
        if self._started:
            return

        self._workers = [
            asyncio.create_task(self._worker(), name=f"ai-worker-{index}")
            for index in range(self.max_parallel_requests)
        ]
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return

        for _ in self._workers:
            await self._queue.put(None)

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    def get_runtime_stats(self) -> dict[str, int | float | bool]:
        stats: dict[str, int | float | bool] = {
            "started": self._started,
            "queue_size": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "workers": len(self._workers),
            "busy_workers": self._busy_workers,
            "max_parallel_requests": self.max_parallel_requests,
            "queue_wait_timeout_seconds": self.queue_wait_timeout_seconds,
            "requests_started": self._requests_started,
            "requests_completed": self._requests_completed,
            "requests_failed": self._requests_failed,
            "requests_rejected": self._requests_rejected,
            "requests_queue_timed_out": self._requests_queue_timed_out,
            "last_queue_wait_ms": self._last_queue_wait_ms,
            "max_queue_wait_ms": self._max_queue_wait_ms,
            "last_run_ms": self._last_run_ms,
            "max_run_ms": self._max_run_ms,
            "crisis_bypass_count": self._crisis_bypass_count,
            "intimacy_clamp_count": self._intimacy_clamp_count,
            "reengagement_clamped_count": self._reengagement_clamped_count,
        }
        if hasattr(self.client, "get_runtime_stats"):
            for key, value in self.client.get_runtime_stats().items():
                stats[f"openai_{key}"] = value
        return stats

    async def generate_response(
        self,
        user_id: int,
        history: List[Dict[str, str]],
        user_message: str,
        state: Dict[str, Any],
    ) -> AIResult:
        if not self._started:
            raise RuntimeError("AI service is not started")

        if self._queue.full():
            self._requests_rejected += 1
            raise AIBackpressureError("AI request queue is full")

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request = AIRequest(
            history=history,
            user_message=user_message,
            state=state,
            user_id=user_id,
            future=future,
            started_event=asyncio.Event(),
            enqueued_at=time.perf_counter(),
        )
        self._queue.put_nowait(request)
        try:
            await asyncio.wait_for(
                request.started_event.wait(),
                timeout=self.queue_wait_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._requests_queue_timed_out += 1
            future.cancel()
            raise AIBackpressureError("AI request queue wait timed out") from exc
        return await future

    async def _worker(self) -> None:
        while True:
            request = await self._queue.get()

            if request is None:
                self._queue.task_done()
                return

            if request.future.cancelled():
                self._queue.task_done()
                continue

            queue_wait_ms = round((time.perf_counter() - request.enqueued_at) * 1000, 1)
            self._last_queue_wait_ms = queue_wait_ms
            self._max_queue_wait_ms = max(self._max_queue_wait_ms, queue_wait_ms)
            request.started_event.set()
            started = time.perf_counter()
            self._busy_workers += 1
            self._requests_started += 1

            try:
                result = await self._generate_response_impl(
                    history=request.history,
                    user_message=request.user_message,
                    state=request.state,
                    user_id=request.user_id,
                )
                self._requests_completed += 1
                if not request.future.done():
                    request.future.set_result(result)
            except Exception as exc:
                self._requests_failed += 1
                if not request.future.done():
                    request.future.set_exception(exc)
            finally:
                run_ms = round((time.perf_counter() - started) * 1000, 1)
                self._last_run_ms = run_ms
                self._max_run_ms = max(self._max_run_ms, run_ms)
                self._busy_workers = max(0, self._busy_workers - 1)
                self._queue.task_done()

    async def _generate_response_impl(
        self,
        history: List[Dict[str, str]],
        user_message: str,
        state: Dict[str, Any],
        user_id: int,
    ) -> AIResult:
        runtime_settings = self.settings_service.get_runtime_settings()
        ai_settings = runtime_settings["ai"]
        memory_enriched_state = self.keyword_memory_service.apply(state.copy(), user_message)
        memory_enriched_state = self.human_memory_service.apply_user_message(
            memory_enriched_state,
            user_message,
        )
        new_state = self.state_engine.update_state(memory_enriched_state, user_message)
        active_mode = self._resolve_effective_mode(new_state, runtime_settings)
        crisis_signal = detect_crisis_signal(user_message)
        if crisis_signal == "direct_self_harm":
            logger.warning("[AI] user_id=%s crisis_signal=%s", user_id, crisis_signal)
            self._crisis_bypass_count += 1
            crisis_response = build_crisis_support_response(crisis_signal)
            new_state = self.human_memory_service.apply_assistant_message(
                new_state,
                crisis_response,
                source="reply",
            )
            return AIResult(
                response=crisis_response,
                new_state=new_state,
                tokens_used=None,
            )
        if crisis_signal is not None:
            logger.info("[AI] user_id=%s crisis_signal=%s no_bypass", user_id, crisis_signal)

        ai_profile = resolve_ai_profile(ai_settings, active_mode)
        access_level = self.access_engine.update_access_level(new_state)
        access_decision = self.access_engine.evaluate_access(
            state=new_state,
            access_level=access_level,
            active_mode=active_mode,
            user_message=user_message,
        )
        access_level = str(access_decision["level"])
        if bool(access_decision.get("clamped")):
            self._intimacy_clamp_count += 1
        memory_messages = await self.memory_engine.build_context(
            history,
            max_tokens=ai_profile["memory_max_tokens"],
        )
        memory_context = await self._build_memory_context(
            new_state,
            user_id=user_id,
            history=history,
        )
        grounding_kind = self.keyword_memory_service.detect_grounding_need(user_message)

        logger.debug(
            "[AI] user_id=%s mode=%s access=%s history_messages=%s queue=%s",
            user_id,
            active_mode,
            access_level,
            len(memory_messages),
            self._queue.qsize(),
        )

        system_prompt = self.prompt_builder.build_system_prompt(
            state=new_state,
            access_level=access_level,
            active_mode=active_mode,
            memory_context=memory_context,
            user_message=user_message,
            extra_instruction=ai_profile["prompt_suffix"],
        )

        if self._should_log_full_prompt(user_id, ai_settings):
            logger.debug(
                "[AI PROMPT] user_id=%s\n%s",
                user_id,
                redact_prompt_for_log(system_prompt),
            )

        if grounding_kind is not None:
            logger.info("[AI] user_id=%s grounding=%s", user_id, grounding_kind)
            grounding_response = self.keyword_memory_service.build_grounding_response(grounding_kind)
            new_state = self.human_memory_service.apply_assistant_message(
                new_state,
                grounding_response,
                source="reply",
            )
            return AIResult(
                response=grounding_response,
                new_state=new_state,
                tokens_used=None,
            )

        messages = (
            [{"role": "system", "content": system_prompt}]
            + memory_messages
            + [{"role": "user", "content": user_message.strip()}]
        )

        response_text, tokens_used = await self._call_with_retry(
            messages,
            ai_settings=ai_settings,
            ai_profile=ai_profile,
            user_id=user_id,
        )
        if not response_text.strip():
            logger.warning("[AI] Empty response from model, using fallback")
            response_text = self.EMPTY_RESPONSE_FALLBACK

        chat_settings = runtime_settings.get("chat", {})
        response_text = self._apply_ptsd_response_contract(
            response_text,
            active_mode=active_mode,
            emotional_tone=str(new_state.get("emotional_tone") or "neutral"),
            enabled=bool(chat_settings.get("response_guardrails_enabled", True)),
            blocked_phrases=list(chat_settings.get("response_guardrail_blocked_phrases") or []),
            user_id=user_id,
            source="reply",
        )

        new_state = self.human_memory_service.apply_assistant_message(
            new_state,
            response_text,
            source="reply",
        )

        return AIResult(
            response=response_text,
            new_state=new_state,
            tokens_used=tokens_used,
        )

    async def generate_reengagement(
        self,
        *,
        user_id: int,
        history: List[Dict[str, str]],
        state: Dict[str, Any],
    ) -> AIResult:
        runtime_settings = self.settings_service.get_runtime_settings()
        ai_settings = runtime_settings["ai"]
        engagement_settings = runtime_settings["engagement"]
        active_mode = self._resolve_effective_mode(state.copy(), runtime_settings)
        ai_profile = resolve_ai_profile(ai_settings, active_mode)
        access_level = self.access_engine.update_access_level(state)
        access_decision = self.access_engine.evaluate_access(
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            user_message="",
            is_proactive=True,
        )
        access_level = str(access_decision["level"])
        if bool(access_decision.get("clamped")):
            self._reengagement_clamped_count += 1
        memory_messages = await self.memory_engine.build_context(
            history,
            max_tokens=ai_profile["memory_max_tokens"],
        )
        memory_context = await self._build_memory_context(
            state,
            user_id=user_id,
            history=history,
        )
        relationship = (state or {}).get("relationship_state", {})
        last_user_message_at = relationship.get("last_user_message_at")
        hours_silent = self.human_memory_service.hours_since_iso(last_user_message_at, fallback=24)
        callback_context = self.human_memory_service.get_reengagement_context(state)
        callback_topic = callback_context.get("callback_hint") or callback_context.get("topic") or ""

        system_prompt = self.prompt_builder.build_system_prompt(
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            memory_context=memory_context,
            extra_instruction=(
                (ai_profile["prompt_suffix"] + "\n\n") if ai_profile["prompt_suffix"] else ""
            )
            + self.human_memory_service.build_reengagement_prompt(
                state,
                hours_silent=hours_silent,
                active_mode=active_mode,
            ),
        )

        if self._should_log_full_prompt(user_id, ai_settings):
            logger.debug(
                "[AI REENGAGE PROMPT] user_id=%s\n%s",
                user_id,
                redact_prompt_for_log(system_prompt),
            )

        messages = (
            [{"role": "system", "content": system_prompt}]
            + memory_messages
            + [{"role": "user", "content": "Сформулируй одно живое сообщение первой инициативы."}]
        )
        response_text, tokens_used = await self._call_with_retry(
            messages,
            ai_settings=ai_settings,
            ai_profile=ai_profile,
            user_id=user_id,
        )
        if not response_text.strip():
            response_text = self.EMPTY_RESPONSE_FALLBACK
        chat_settings = runtime_settings.get("chat", {})
        response_text = self._apply_ptsd_response_contract(
            response_text,
            active_mode=active_mode,
            emotional_tone=str(state.get("emotional_tone") or "neutral"),
            enabled=bool(chat_settings.get("response_guardrails_enabled", True)),
            blocked_phrases=list(chat_settings.get("response_guardrail_blocked_phrases") or []),
            user_id=user_id,
            source="reengagement",
        )

        new_state = self.human_memory_service.apply_assistant_message(
            state.copy(),
            response_text,
            source="reengagement",
        )
        new_state = self.human_memory_service.mark_reengagement_callback(
            new_state,
            callback_topic,
        )
        new_state["adaptive_mode"] = active_mode

        logger.info(
            "[AI REENGAGE] user_id=%s mode=%s silent_hours=%s batch_window_days=%s",
            user_id,
            active_mode,
            hours_silent,
            engagement_settings["reengagement_recent_window_days"],
        )

        return AIResult(response=response_text, new_state=new_state, tokens_used=tokens_used)

    def _should_log_full_prompt(
        self,
        user_id: int,
        ai_settings: dict[str, Any],
    ) -> bool:
        if not self.debug:
            return False

        log_full_prompt = bool(ai_settings.get("log_full_prompt", self.log_full_prompt))
        debug_prompt_user_id = ai_settings.get(
            "debug_prompt_user_id",
            self.debug_prompt_user_id,
        )

        if not log_full_prompt:
            return False

        if debug_prompt_user_id is None:
            return True

        return int(debug_prompt_user_id) == user_id

    async def _call_with_retry(
        self,
        messages: List[Dict[str, str]],
        *,
        ai_settings: dict[str, Any],
        ai_profile: dict[str, Any],
        user_id: int,
    ) -> tuple[str, int | None]:
        last_exception = None
        max_retries = int(ai_profile.get("max_retries", self.max_retries))
        timeout_seconds = int(ai_profile.get("timeout_seconds", self.timeout_seconds))
        model = str(ai_profile.get("model") or self.client.model)
        temperature = float(ai_profile.get("temperature", self.client.temperature))
        top_p = float(ai_settings.get("top_p", 1.0))
        frequency_penalty = float(ai_settings.get("frequency_penalty", 0.0))
        presence_penalty = float(ai_settings.get("presence_penalty", 0.0))
        max_completion_tokens = int(
            ai_profile.get("max_completion_tokens", ai_settings.get("max_completion_tokens", 400)),
        )
        reasoning_effort = str(ai_settings.get("reasoning_effort") or "").strip() or None
        verbosity = str(ai_settings.get("verbosity") or "").strip() or None
        truncation_retries = 0

        attempt = 0
        while attempt <= max_retries:
            try:
                response_text, tokens_used, finish_reason = await asyncio.wait_for(
                    self._generate_with_optional_meta(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        top_p=top_p,
                        frequency_penalty=frequency_penalty,
                        presence_penalty=presence_penalty,
                        max_completion_tokens=max_completion_tokens,
                        reasoning_effort=reasoning_effort,
                        verbosity=verbosity,
                        user=str(user_id),
                    ),
                    timeout=timeout_seconds,
                )
                if (
                    finish_reason == "length"
                    and truncation_retries < self.MAX_TRUNCATION_RETRIES
                    and max_completion_tokens < self.MAX_TRUNCATION_COMPLETION_TOKENS
                ):
                    next_limit = min(
                        self.MAX_TRUNCATION_COMPLETION_TOKENS,
                        max_completion_tokens * self.TRUNCATION_TOKEN_MULTIPLIER,
                    )
                    if next_limit > max_completion_tokens:
                        logger.warning(
                            "[AI] user_id=%s response truncated at %s tokens, retrying with %s",
                            user_id,
                            max_completion_tokens,
                            next_limit,
                        )
                        max_completion_tokens = next_limit
                        truncation_retries += 1
                        continue
                return response_text, tokens_used
            except asyncio.TimeoutError as exc:
                last_exception = exc
            except Exception as exc:
                last_exception = exc

            await asyncio.sleep(0.5 * (attempt + 1))
            attempt += 1

        raise RuntimeError("AI call failed after retries") from last_exception

    async def _generate_with_optional_meta(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        top_p: float,
        frequency_penalty: float,
        presence_penalty: float,
        max_completion_tokens: int,
        reasoning_effort: str | None,
        verbosity: str | None,
        user: str,
    ) -> tuple[str, int | None, str | None]:
        payload = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "top_p": top_p,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "max_completion_tokens": max_completion_tokens,
            "reasoning_effort": reasoning_effort,
            "verbosity": verbosity,
            "user": user,
        }
        if hasattr(self.client, "generate_with_meta"):
            return await self.client.generate_with_meta(**payload)

        text, tokens_used = await self.client.generate(**payload)
        return text, tokens_used, None

    async def _build_memory_context(
        self,
        state: dict[str, Any],
        *,
        user_id: int,
        history: list[Any] | None = None,
    ) -> str:
        parts = [
            await self.long_term_memory_service.build_prompt_context(user_id),
            self.keyword_memory_service.build_prompt_context(state, history=history),
            self.human_memory_service.build_prompt_context(state),
        ]
        return "\n".join(part.strip() for part in parts if part and part.strip())

    def _apply_ptsd_response_contract(
        self,
        text: str,
        *,
        active_mode: str,
        emotional_tone: str,
        enabled: bool,
        blocked_phrases: list[str],
        user_id: int,
        source: str,
    ) -> str:
        response_text = apply_ptsd_response_guardrails(
            text,
            active_mode=active_mode,
            emotional_tone=emotional_tone,
            enabled=enabled,
            blocked_phrases=blocked_phrases,
        )
        if not enabled:
            return response_text
        if active_mode not in {"free_talk", "ptsd", "comfort"}:
            return response_text
        if emotional_tone not in {"overwhelmed", "anxious", "guarded"}:
            return response_text

        style_audit = analyze_response_style(
            response_text,
            blocked_phrases=blocked_phrases,
        )
        if not style_audit["looks_overloaded"]:
            return response_text

        logger.info(
            "[AI PTSD CLAMP] user_id=%s source=%s mode=%s tone=%s length=%s sentences=%s",
            user_id,
            source,
            active_mode,
            emotional_tone,
            style_audit["length"],
            style_audit.get("sentence_count", 0),
        )
        tightened = tighten_ptsd_response(response_text)
        return apply_ptsd_response_guardrails(
            tightened,
            active_mode=active_mode,
            emotional_tone=emotional_tone,
            enabled=enabled,
            blocked_phrases=blocked_phrases,
        )

    def _resolve_effective_mode(
        self,
        state: dict[str, Any],
        runtime_settings: dict[str, Any],
    ) -> str:
        active_mode = str((state or {}).get("active_mode") or "base")
        engagement_settings = runtime_settings.get("engagement", {})
        if not engagement_settings.get("adaptive_mode_enabled", True):
            state["adaptive_mode"] = active_mode
            return active_mode

        suggested_mode = self.human_memory_service.suggest_mode(state, active_mode)
        state["adaptive_mode"] = suggested_mode
        return suggested_mode
