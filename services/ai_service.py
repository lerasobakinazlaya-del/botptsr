import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from services.ai_profile_service import resolve_ai_profile
from services.conversation_driver import (
    apply_driver_guardrails,
    build_reflection,
    detect_intent,
    is_driver_safe_context,
    resolve_driver_stage,
    resolve_followup_entry,
    wants_full_reveal,
)
from services.conversation_engine_v2 import ConversationEngineV2
from services.emotional_hooks import ensure_open_loop, inject_hook, select_hook
from services.prompt_safety import redact_prompt_for_log
from services.response_guardrails import (
    analyze_response_style,
    apply_human_style_guardrails,
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
        conversation_engine=None,
        memory_profile_service=None,
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
        self.memory_profile_service = memory_profile_service
        self.prompt_builder = prompt_builder
        self.access_engine = access_engine
        self.settings_service = settings_service
        self.conversation_engine = conversation_engine or ConversationEngineV2(settings_service)
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

        ai_profile = self._apply_fast_lane_profile(
            resolve_ai_profile(ai_settings, active_mode),
            user_message=user_message,
            active_mode=active_mode,
        )
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
        driver_context = self._resolve_conversation_driver_context(
            user_message=user_message,
            state=new_state,
            runtime_settings=runtime_settings,
            crisis_signal=crisis_signal,
            grounding_kind=grounding_kind,
        )

        logger.debug(
            "[AI] user_id=%s mode=%s access=%s history_messages=%s queue=%s",
            user_id,
            active_mode,
            access_level,
            len(memory_messages),
            self._queue.qsize(),
        )

        system_prompt = self.conversation_engine.build_system_prompt(
            state=new_state,
            access_level=access_level,
            active_mode=active_mode,
            memory_context=memory_context,
            user_message=user_message,
            base_instruction=self._compose_reply_instruction(
                base_instruction=ai_profile["prompt_suffix"],
                user_message=user_message,
                history=history,
                driver_context=driver_context,
            ),
            history=history,
            access_profile=access_decision.get("budget"),
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
        response_text = self.conversation_engine.guard_response(
            response_text,
            user_message=user_message,
        )
        if driver_context is not None:
            response_text = self._apply_conversation_driver_guardrails(
                response_text,
                user_message=user_message,
                state=new_state,
                driver_context=driver_context,
            )
        response_text, hook_used = self._apply_emotional_hook(
            response_text,
            state=new_state,
            user_message=user_message,
            source="reply",
        )
        if hook_used:
            new_state["last_hook"] = hook_used
        if driver_context is not None:
            new_state["last_detected_intent"] = str(driver_context["intent"])
            new_state["last_driver_question_id"] = str(driver_context["question_id"])

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
        reengagement_style = dict(engagement_settings.get("reengagement_style") or {})
        active_mode = self._resolve_effective_mode(state.copy(), runtime_settings)
        ai_profile = self._apply_reengagement_profile(
            resolve_ai_profile(ai_settings, active_mode),
            reengagement_style=reengagement_style,
        )
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

        system_prompt = self.conversation_engine.build_system_prompt(
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            memory_context=memory_context,
            user_message="Сформулируй одно живое сообщение первой инициативы.",
            base_instruction=(
                (ai_profile["prompt_suffix"] + "\n\n") if ai_profile["prompt_suffix"] else ""
            )
            + self.human_memory_service.build_reengagement_prompt(
                state,
                hours_silent=hours_silent,
                active_mode=active_mode,
                style_settings=reengagement_style,
            ),
            history=history,
            is_reengagement=True,
            access_profile=access_decision.get("budget"),
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
        response_text = self.conversation_engine.guard_response(
            response_text,
            user_message="Сформулируй одно живое сообщение первой инициативы.",
            force_dialogue_pull=bool(reengagement_style.get("allow_question", True)),
        )
        response_text, hook_used = self._apply_emotional_hook(
            response_text,
            state=state,
            user_message="",
            source="reengagement",
        )

        new_state = self.human_memory_service.apply_assistant_message(
            state.copy(),
            response_text,
            source="reengagement",
        )
        if hook_used:
            new_state["last_hook"] = hook_used
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
        reasoning_effort = (
            str(ai_profile.get("reasoning_effort_override") or ai_settings.get("reasoning_effort") or "").strip()
            or None
        )
        verbosity = (
            str(ai_profile.get("verbosity_override") or ai_settings.get("verbosity") or "").strip()
            or None
        )
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
            await self.memory_profile_service.build_prompt_context(
                user_id=user_id,
                state=state,
                history=history,
            )
            if self.memory_profile_service is not None
            else "",
            await self.long_term_memory_service.build_prompt_context(user_id)
            if self.memory_profile_service is None
            else "",
            self.keyword_memory_service.build_prompt_context(state, history=history)
            if self.memory_profile_service is None
            else "",
            self.human_memory_service.build_prompt_context(state)
            if self.memory_profile_service is None
            else "",
        ]
        return "\n".join(part.strip() for part in parts if part and part.strip())

    def _compose_reply_instruction(
        self,
        *,
        base_instruction: str,
        user_message: str,
        history: list[dict[str, str]],
        driver_context: dict[str, Any] | None,
    ) -> str:
        parts = [
            str(base_instruction or "").strip(),
            self._build_continuation_instruction(
                user_message=user_message,
                history=history,
            ),
            self._build_risky_topic_instruction(user_message),
            self._build_human_companion_instruction(
                user_message=user_message,
                history=history,
            ),
            self._build_conversation_driver_instruction(driver_context),
        ]
        return "\n\n".join(part for part in parts if part)

    def _build_continuation_instruction(
        self,
        *,
        user_message: str,
        history: list[dict[str, str]],
    ) -> str:
        lowered = " ".join(str(user_message or "").lower().split())
        if not lowered:
            return ""

        if not self._looks_like_continuation_request(lowered):
            return ""

        last_assistant_message = ""
        for item in reversed(history or []):
            if str(item.get("role") or "") == "assistant":
                last_assistant_message = str(item.get("content") or "")
                break

        if not last_assistant_message.strip():
            return (
                "The user asked you to continue the previous thought. Continue directly instead of restarting, "
                "and do not open with a new follow-up question."
            )

        matches = re.findall(r"(?m)^\s*(\d+)[.)]\s+", last_assistant_message)
        if not matches:
            return (
                "The user asked you to continue the previous answer. Continue directly instead of restarting, "
                "and do not open with a new follow-up question."
            )

        next_number = max(int(value) for value in matches) + 1
        return (
            "The user asked you to continue an existing numbered list. "
            f"Continue directly from item {next_number} instead of restarting, do not repeat earlier items, "
            "and finish the remaining items in this reply if possible."
        )
    def _build_risky_topic_instruction(self, user_message: str) -> str:
        lowered = " ".join(str(user_message or "").lower().split())
        if not lowered:
            return ""

        drug_hints = (
            "меф",
            "мефедрон",
            "2cb",
            "2-cb",
            "наркот",
            "веществ",
            "под ",
            "употребля",
        )
        sexual_hints = (
            "секс",
            "группов",
            "оргия",
            "тройнич",
        )
        if not any(hint in lowered for hint in drug_hints):
            return ""
        if not any(hint in lowered for hint in sexual_hints):
            return ""

        return (
            "Do not romanticize altered-state scenarios with blurred control. "
            "Do not provide step-by-step use, mixing, or escalation instructions. "
            "Stay on harm reduction: consent, boundaries, stop-signal, sober oversight, mixing risks, what to do if someone feels bad, and aftercare."
        )
    def _build_human_companion_instruction(
        self,
        *,
        user_message: str,
        history: list[dict[str, str]],
    ) -> str:
        lowered = " ".join(str(user_message or "").lower().split())
        if not lowered:
            return ""

        instructions = [
            "Sound like a vivid human companion, not a cautious interviewer or therapy script.",
            "Do not open with canned reassurance or soft meta-prefaces if you can go straight to the point.",
        ]

        if self._user_explicitly_invites_questions(lowered):
            instructions.append(
                "The user explicitly invited questions. You may ask one precise follow-up question, but only after your own point."
            )
        else:
            instructions.append(
                "By default, do not ask a follow-up question if you can answer well without it."
            )

        if self._looks_like_answer_first_request(lowered):
            instructions.extend(
                [
                    "The user wants an answer-first reply. Put the actual answer in the first sentence.",
                    "Do not end with a generic question like 'how do you see it?' or 'what do you think?'.",
                    "If useful, speak plainly and take a position instead of hedging.",
                ]
            )

        if self._assistant_has_been_question_heavy(history):
            instructions.append(
                "Recent turns were too question-heavy. Keep initiative in this reply and do not turn it back into an interview."
            )

        return " ".join(instructions)
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

    def _apply_human_companion_guardrails(
        self,
        text: str,
        *,
        user_message: str,
    ) -> str:
        lowered = " ".join(str(user_message or "").lower().split())
        return apply_human_style_guardrails(
            text,
            answer_first=self._looks_like_answer_first_request(lowered),
            allow_follow_up_question=self._user_explicitly_invites_questions(lowered),
            user_message=user_message,
        )

    def _apply_emotional_hook(
        self,
        text: str,
        *,
        state: dict[str, Any],
        user_message: str,
        source: str,
    ) -> tuple[str, str]:
        response_text = " ".join(str(text or "").split()).strip()
        if not response_text:
            return response_text, ""

        if not self._should_apply_emotional_hook(
            user_message=user_message,
            state=state,
            source=source,
        ):
            return response_text, ""

        strategy = "reengagement" if source == "reengagement" else "auto"
        hook = select_hook(state, strategy)
        if not hook:
            return response_text, ""

        hooked_text = inject_hook(response_text, hook)
        if hooked_text == response_text:
            return response_text, ""

        return ensure_open_loop(hooked_text), hook

    def _build_conversation_driver_instruction(self, driver_context: dict[str, Any] | None) -> str:
        if driver_context is None:
            return ""
        return (
            "Conversation driver override:\n"
            "- This override has priority for this turn when it conflicts with generic no-question defaults.\n"
            f"- detected intent: {driver_context['intent']}\n"
            f"- engagement stage: {driver_context['stage']}\n"
            f"- selected question id: {driver_context['question_id']}\n"
            f"- reflection: {driver_context['reflection']}\n"
            f"- exact follow-up question: {driver_context['question']}\n"
            "- Shape the reply as: reflect the user's intent, then land on the exact follow-up question above.\n"
            "- Split the question between 2-3 motives.\n"
            "- Max 3 sentences.\n"
            "- Do not use bullet lists or numbered lists unless the user explicitly asked for a list.\n"
            "- End with the selected question or a compatible open loop.\n"
            "- Do not fully close the topic; keep the dialogue moving."
        )

    def _apply_conversation_driver_guardrails(
        self,
        text: str,
        *,
        user_message: str,
        state: dict[str, Any],
        driver_context: dict[str, Any],
    ) -> str:
        return apply_driver_guardrails(
            text,
            user_message=user_message,
            state=state,
            intent=str(driver_context["intent"]),
            followup_question=str(driver_context["question"]),
        )

    def _resolve_conversation_driver_context(
        self,
        *,
        user_message: str,
        state: dict[str, Any],
        runtime_settings: dict[str, Any],
        crisis_signal: str | None,
        grounding_kind: str | None,
    ) -> dict[str, Any] | None:
        if not self._conversation_driver_enabled(runtime_settings):
            return None
        normalized_message = self._normalize(user_message)
        if not normalized_message:
            return None
        intent = detect_intent(user_message)
        if self._should_skip_conversation_driver(
            normalized_message=normalized_message,
            user_message=user_message,
            state=state,
            crisis_signal=crisis_signal,
            grounding_kind=grounding_kind,
            intent=intent,
        ):
            return None

        stage = resolve_driver_stage(state)
        entry = resolve_followup_entry(intent, state)
        return {
            "intent": intent,
            "stage": stage,
            "question_id": str(entry["id"]),
            "question": str(entry["text"]),
            "reflection": build_reflection(intent, state),
        }

    def _should_skip_conversation_driver(
        self,
        *,
        normalized_message: str,
        user_message: str,
        state: dict[str, Any],
        crisis_signal: str | None,
        grounding_kind: str | None,
        intent: str,
    ) -> bool:
        if crisis_signal is not None or grounding_kind is not None:
            return True
        if not is_driver_safe_context(user_message, state):
            return True
        if wants_full_reveal(user_message):
            return True
        if self._looks_like_continuation_request(normalized_message):
            return True
        if self._looks_like_scene_request(normalized_message):
            return True
        if intent == "explicit_request" and self._looks_like_answer_first_request(normalized_message):
            return not self._looks_like_hook_turn(normalized_message)
        return False

    def _conversation_driver_enabled(self, runtime_settings: dict[str, Any]) -> bool:
        engagement_settings = runtime_settings.get("engagement", {})
        if engagement_settings.get("conversation_driver_enabled") is None:
            return bool(engagement_settings.get("adaptive_mode_enabled", True))
        return bool(engagement_settings.get("conversation_driver_enabled"))

    def _should_apply_emotional_hook(
        self,
        *,
        user_message: str,
        state: dict[str, Any],
        source: str,
    ) -> bool:
        if str(state.get("emotional_tone") or "neutral") in {"overwhelmed", "anxious", "guarded"}:
            return False

        normalized_message = self._normalize(user_message)
        if source == "reengagement":
            return True

        if not normalized_message:
            return False
        if self._looks_like_continuation_request(normalized_message):
            return False
        if self._looks_like_scene_request(normalized_message):
            return False
        if self._looks_like_answer_first_request(normalized_message) and not self._looks_like_hook_turn(normalized_message):
            return False

        return self._looks_like_hook_turn(normalized_message) or len(normalized_message) <= 140

    def _looks_like_answer_first_request(self, text: str) -> bool:
        answer_hints = (
            "как",
            "что делать",
            "что лучше",
            "что думаешь",
            "расскажи",
            "объясни",
            "составь",
            "распиши",
            "продолж",
            "далее",
            "дальше",
            "подскажи",
            "помоги",
            "план",
            "инструкция",
            "по делу",
            "прямо",
        )
        return any(hint in text for hint in answer_hints)
    def _user_explicitly_invites_questions(self, text: str) -> bool:
        question_hints = (
            "спрашивай",
            "задавай вопросы",
            "можешь спрашивать",
            "спроси меня",
            "поспрашивай",
        )
        return any(hint in text for hint in question_hints)
    def _apply_fast_lane_profile(
        self,
        ai_profile: dict[str, Any],
        *,
        user_message: str,
        active_mode: str,
    ) -> dict[str, Any]:
        normalized = self._normalize(user_message)
        fast_lane = self._get_fast_lane_settings()
        if not bool(fast_lane.get("enabled", True)):
            return ai_profile
        if not self._should_use_fast_lane(normalized, active_mode=active_mode):
            return ai_profile

        optimized = dict(ai_profile)
        is_continuation = self._looks_like_continuation_request(normalized)
        is_scene = self._looks_like_scene_request(normalized)
        is_hook_turn = self._looks_like_hook_turn(normalized)

        profile_name = (
            "hook" if is_hook_turn else "continuation" if is_continuation else "scene" if is_scene else "generic"
        )
        optimized["max_completion_tokens"] = min(
            int(optimized.get("max_completion_tokens", 220)),
            int(fast_lane.get(f"{profile_name}_max_completion_tokens", 200)),
        )
        optimized["memory_max_tokens"] = min(
            int(optimized.get("memory_max_tokens", 1200)),
            int(fast_lane.get(f"{profile_name}_memory_max_tokens", 900)),
        )
        optimized["history_message_limit"] = min(
            int(optimized.get("history_message_limit", 20)),
            int(fast_lane.get(f"{profile_name}_history_message_limit", 10)),
        )
        optimized["timeout_seconds"] = min(
            int(optimized.get("timeout_seconds", self.timeout_seconds)),
            int(fast_lane.get(f"{profile_name}_timeout_seconds", 12)),
        )
        optimized["max_retries"] = min(
            int(optimized.get("max_retries", self.max_retries)),
            int(fast_lane.get(f"{profile_name}_max_retries", 1)),
        )
        if bool(fast_lane.get("force_low_verbosity", True)):
            optimized["verbosity_override"] = "low"
        if bool(fast_lane.get("force_low_reasoning", True)) and not str(
            optimized.get("reasoning_effort_override") or ""
        ).strip():
            optimized["reasoning_effort_override"] = "low"
        return optimized

    def _apply_reengagement_profile(
        self,
        ai_profile: dict[str, Any],
        *,
        reengagement_style: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        optimized = dict(ai_profile)
        style = reengagement_style or {}
        optimized["max_completion_tokens"] = min(
            int(optimized.get("max_completion_tokens", 220)),
            int(style.get("max_completion_tokens", 120)),
        )
        optimized["memory_max_tokens"] = min(
            int(optimized.get("memory_max_tokens", 1200)),
            700,
        )
        optimized["history_message_limit"] = min(
            int(optimized.get("history_message_limit", 20)),
            8,
        )
        optimized["timeout_seconds"] = min(
            int(optimized.get("timeout_seconds", self.timeout_seconds)),
            8,
        )
        optimized["max_retries"] = 0
        optimized["verbosity_override"] = "low"
        optimized["reasoning_effort_override"] = "low"
        return optimized

    def _get_fast_lane_settings(self) -> dict[str, Any]:
        runtime_settings = self.settings_service.get_runtime_settings()
        return dict(runtime_settings.get("ai", {}).get("fast_lane") or {})

    def _should_use_fast_lane(self, text: str, *, active_mode: str) -> bool:
        if active_mode in {"mentor", "ptsd"}:
            return False
        if self._looks_like_hook_turn(text):
            return True
        if self._looks_like_continuation_request(text):
            return True
        if self._looks_like_scene_request(text):
            return True
        return len(text) <= 140 and self._looks_like_answer_first_request(text)

    def _looks_like_hook_turn(self, text: str) -> bool:
        if not text:
            return False
        if len(text.split()) > 14:
            return False
        hook_hints = (
            "что думаешь",
            "как тебе",
            "или",
            "а если",
            "почему",
            "хочу",
            "нравится",
            "цепляет",
            "заводит",
            "стоит ли",
        )
        return text.endswith("?") or any(hint in text for hint in hook_hints)
    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(str(text or "").lower().split())

    @staticmethod
    def _looks_like_continuation_request(text: str) -> bool:
        return bool(
            re.fullmatch(
                "(ок[,.!]?\s*)?(далее|дальше|продолжай|продолжи|и дальше|давай)",
                text,
            )
        )
    @staticmethod
    def _looks_like_scene_request(text: str) -> bool:
        hints = (
            "как это должно проходить",
            "как это должно быть",
            "опиши",
            "сценарий",
            "атмосфер",
            "техно",
            "белье",
            "оргия",
            "хим",
            "мжмж",
            "жмж",
            "ммж",
            "втроем",
            "вчетвером",
            "фантаз",
        )
        return any(hint in text for hint in hints)
    def _assistant_has_been_question_heavy(self, history: list[dict[str, str]]) -> bool:
        assistant_messages = [
            str(self._history_item_field(item, "content") or "")
            for item in history or []
            if str(self._history_item_field(item, "role") or "") == "assistant"
        ]
        recent = assistant_messages[-2:]
        if not recent:
            return False
        return sum(message.count("?") for message in recent) >= 2

    @staticmethod
    def _history_item_field(item: Any, field: str) -> Any:
        if isinstance(item, dict):
            return item.get(field)
        return getattr(item, field, None)

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
