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


def looks_like_full_translation_request(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    if not normalized:
        return False
    translation_hints = (
        "переведи",
        "перевод",
        "перевести",
        "как переведешь",
        "как ты переведешь",
    )
    completeness_hints = (
        "целиком",
        "полностью",
        "весь текст",
        "текст целиком",
        "до конца",
        "все строки",
    )
    explanation_hints = (
        "смысл",
        "объясни",
        "разбери",
        "как видишь",
        "что значит",
    )
    has_translation = any(hint in normalized for hint in translation_hints)
    has_completeness = any(hint in normalized for hint in completeness_hints)
    has_explanation = any(hint in normalized for hint in explanation_hints)
    looks_like_pasted_source = len(str(text or "")) >= 700 or str(text or "").count("\n") >= 6
    return has_translation and (has_completeness or has_explanation or looks_like_pasted_source)


def looks_like_long_task_request(text: str) -> bool:
    raw = str(text or "").strip()
    normalized = " ".join(raw.lower().split())
    if not normalized:
        return False
    if looks_like_full_translation_request(raw):
        return True
    long_answer_hints = (
        "разбери",
        "объясни",
        "реши",
        "составь",
        "проанализируй",
        "план",
        "архитектур",
        "код",
        "ошибк",
        "почему",
        "как сделать",
        "подробно",
        "целиком",
        "полностью",
        "до конца",
    )
    looks_big = len(raw) >= 900 or raw.count("\n") >= 8
    looks_medium_with_task = len(raw) >= 600 and any(hint in normalized for hint in long_answer_hints)
    return looks_big or looks_medium_with_task


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
    subscription_plan: str
    future: asyncio.Future
    started_event: asyncio.Event
    enqueued_at: float


class AIBackpressureError(RuntimeError):
    pass


class AIService:
    FIRST_INITIATIVE_USER_PROMPT = "Напиши одно живое инициативное сообщение на русском после паузы."
    REENGAGEMENT_LANGUAGE_CONTRACT = (
        "Языковой контракт для внешнего сообщения:\n"
        "- Ответ должен быть только на русском языке.\n"
        "- Не используй английские приветствия, связки или вопросы.\n"
        "- Если внутренние инструкции написаны на английском, все равно переформулируй итог по-русски."
    )
    EMPTY_RESPONSE_FALLBACK = (
        "Я рядом. Попробуй написать это чуть иначе, и я отвечу точнее."
    )
    MAX_TRUNCATION_RETRIES = 1
    TRUNCATION_TOKEN_MULTIPLIER = 2
    MAX_TRUNCATION_COMPLETION_TOKENS = 1200
    LONG_TASK_MIN_COMPLETION_TOKENS = 950
    TRANSLATION_REQUEST_MIN_COMPLETION_TOKENS = LONG_TASK_MIN_COMPLETION_TOKENS

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
        subscription_plan: str = "free",
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
            subscription_plan=subscription_plan,
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
                    subscription_plan=getattr(request, "subscription_plan", "free"),
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
        subscription_plan: str = "free",
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

        translation_request = self._looks_like_full_translation_request(user_message)
        long_task_request = self._looks_like_long_task_request(user_message)
        ai_profile = resolve_ai_profile(ai_settings, active_mode, subscription_plan)
        if long_task_request:
            ai_profile = self._apply_long_task_profile(ai_profile)
        else:
            ai_profile = self._apply_fast_lane_profile(
                ai_profile,
                user_message=user_message,
                active_mode=active_mode,
                subscription_plan=subscription_plan,
            )
            ai_profile = self._apply_cost_control_profile(
                ai_profile,
                runtime_settings=runtime_settings,
                user_message=user_message,
                subscription_plan=subscription_plan,
            )
        history_for_context = self._limit_history_messages(
            history,
            ai_profile["history_message_limit"],
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
        memory_messages = await self._build_memory_messages(
            history_for_context,
            max_tokens=ai_profile["memory_max_tokens"],
            max_messages=ai_profile["history_message_limit"],
        )
        memory_context = await self._build_memory_context(
            new_state,
            user_id=user_id,
            history=history_for_context,
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
            subscription_plan=subscription_plan,
            base_instruction=self._compose_reply_instruction(
                base_instruction=ai_profile["prompt_suffix"],
                user_message=user_message,
                history=history_for_context,
                driver_context=driver_context,
                translation_request=translation_request,
                long_task_request=long_task_request,
            ),
            history=history_for_context,
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
            usage_source="chat",
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
            active_mode=active_mode,
            history=history_for_context,
            crisis_signal=crisis_signal,
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
        response_text = self.conversation_engine.guard_response(
            response_text,
            user_message=user_message,
            active_mode=active_mode,
            history=history_for_context,
            crisis_signal=crisis_signal,
        )
        if driver_context is not None:
            new_state["last_detected_intent"] = str(driver_context["intent"])
            new_state["last_driver_question_id"] = str(driver_context["question_id"])
            if "?" in response_text:
                new_state["driver_question_streak"] = int(new_state.get("driver_question_streak", 0) or 0) + 1
            else:
                new_state["driver_question_streak"] = 0

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
        subscription_plan: str = "free",
    ) -> AIResult:
        runtime_settings = self.settings_service.get_runtime_settings()
        ai_settings = runtime_settings["ai"]
        engagement_settings = runtime_settings["engagement"]
        reengagement_style = dict(engagement_settings.get("reengagement_style") or {})
        active_mode = self._resolve_effective_mode(state.copy(), runtime_settings)
        ai_profile = self._apply_reengagement_profile(
            resolve_ai_profile(ai_settings, active_mode, subscription_plan),
            reengagement_style=reengagement_style,
        )
        history_for_context = self._limit_history_messages(
            history,
            ai_profile["history_message_limit"],
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
        memory_messages = await self._build_memory_messages(
            history_for_context,
            max_tokens=ai_profile["memory_max_tokens"],
            max_messages=ai_profile["history_message_limit"],
        )
        memory_context = await self._build_memory_context(
            state,
            user_id=user_id,
            history=history_for_context,
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
            user_message=self.FIRST_INITIATIVE_USER_PROMPT,
            subscription_plan=subscription_plan,
            base_instruction=(
                (ai_profile["prompt_suffix"] + "\n\n") if ai_profile["prompt_suffix"] else ""
            )
            + self.REENGAGEMENT_LANGUAGE_CONTRACT
            + "\n\n"
            + self.human_memory_service.build_reengagement_prompt(
                state,
                hours_silent=hours_silent,
                active_mode=active_mode,
                style_settings=reengagement_style,
            ),
            history=history_for_context,
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
            + [{"role": "user", "content": self.FIRST_INITIATIVE_USER_PROMPT}]
        )
        response_text, tokens_used = await self._call_with_retry(
            messages,
            ai_settings=ai_settings,
            ai_profile=ai_profile,
            user_id=user_id,
            usage_source="reengagement",
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
            user_message=self.FIRST_INITIATIVE_USER_PROMPT,
            active_mode=active_mode,
            history=history_for_context,
            force_dialogue_pull=bool(reengagement_style.get("allow_question", False)),
        )
        response_text, hook_used = self._apply_emotional_hook(
            response_text,
            state=state,
            user_message="",
            source="reengagement",
        )
        response_text = self.conversation_engine.guard_response(
            response_text,
            user_message=self.FIRST_INITIATIVE_USER_PROMPT,
            active_mode=active_mode,
            history=history_for_context,
            force_dialogue_pull=bool(reengagement_style.get("allow_question", False)),
        )
        repaired_response_text = self._repair_reengagement_language(
            response_text,
            state=state,
            callback_context=callback_context,
            allow_question=bool(reengagement_style.get("allow_question", False)),
        )
        if repaired_response_text != response_text:
            response_text = repaired_response_text
            hook_used = ""

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

    def _repair_reengagement_language(
        self,
        text: str,
        *,
        state: dict[str, Any],
        callback_context: dict[str, str] | None = None,
        allow_question: bool = True,
    ) -> str:
        normalized = str(text or "").strip()
        if normalized and not self._looks_like_english_or_mixed_language(normalized):
            return normalized

        relationship = (state or {}).get("relationship_state") or {}
        context = callback_context or self.human_memory_service.get_reengagement_context(state)
        topic = self._safe_russian_callback(
            context.get("callback_hint") or context.get("topic") or relationship.get("last_user_topic") or ""
        )
        if topic:
            fallback = f"Привет. Вспомнила про {topic}."
            if allow_question:
                fallback += " Как это сейчас у тебя?"
            return fallback
        if allow_question:
            return "Привет. Вспомнила наш разговор. Как ты сейчас?"
        return "Привет. Вспомнила наш разговор и решила тихо вернуться."

    def _looks_like_english_or_mixed_language(self, text: str) -> bool:
        cyrillic_count = len(re.findall(r"[А-Яа-яЁё]", text))
        latin_words = [
            word.lower()
            for word in re.findall(r"\b[A-Za-z][A-Za-z']+\b", text)
            if word.lower()
            not in {
                "ai",
                "api",
                "bot",
                "gpt",
                "openai",
                "telegram",
                "url",
                "http",
                "https",
            }
        ]
        if cyrillic_count and len(latin_words) >= 2:
            return True
        return cyrillic_count == 0 and len(latin_words) >= 3

    def _safe_russian_callback(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" .,:;!?\"'")
        if not text or self._looks_like_english_or_mixed_language(text):
            return ""
        text = re.sub(r"(?i)\b(system|developer|assistant|ignore previous|instructions?)\b", "", text)
        text = re.sub(r"\s+", " ", text).strip(" .,:;!?\"'")
        if len(text) > 80:
            text = text[:77].rstrip(" .,:;!?") + "..."
        return text

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
        usage_source: str,
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
                        usage_context={
                            "source": usage_source,
                            "user_id": user_id,
                        },
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
        usage_context: dict[str, Any] | None = None,
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
            "usage_context": usage_context,
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
        translation_request: bool = False,
        long_task_request: bool = False,
    ) -> str:
        parts = [
            str(base_instruction or "").strip(),
            self._build_full_translation_instruction(user_message) if translation_request else "",
            self._build_long_task_instruction(user_message) if long_task_request and not translation_request else "",
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

    def _build_full_translation_instruction(self, user_message: str) -> str:
        return (
            "Запрос на перевод и разбор:\n"
            "- Если это личный, рабочий или пользовательский текст, переведи его целиком и не ограничивайся первыми строками.\n"
            "- Если это песня, книга, статья или другой вероятно защищенный авторским правом текст, не делай полный перевод всего текста: дай краткий допустимый перевод небольшого фрагмента и подробно перескажи смысл остального своими словами.\n"
            "- После перевода отдельно объясни смысл: конфликт, позицию говорящего, эмоциональную динамику и ключевые образы.\n"
            "- Не обрывай ответ на середине предложения. Если нужно сжать, сжимай объяснение и явно заверши мысль.\n"
            "- Не начинай с извинений и не уходи в общий комментарий вместо перевода."
        )

    def _build_long_task_instruction(self, user_message: str) -> str:
        return (
            "Длинная задача или большое сообщение:\n"
            "- Пользователь дал много контекста и ожидает не короткую реплику, а рабочий разбор.\n"
            "- Дай развернутый ответ с ясной структурой, но без воды: сначала итог/решение, затем шаги, затем важные нюансы.\n"
            "- Используй весь предоставленный контекст; не отвечай только на первую часть сообщения.\n"
            "- Если задача объемная, доведи хотя бы главный сценарий до применимого результата и явно обозначь, что осталось следующим шагом.\n"
            "- Не обрывай ответ на середине предложения."
        )

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
                "Пользователь попросил продолжить предыдущую мысль. Продолжай прямо, не начинай заново "
                "и не открывай ответ новым follow-up вопросом."
            )

        matches = re.findall(r"(?m)^\s*(\d+)[.)]\s+", last_assistant_message)
        if not matches:
            return (
                "Пользователь попросил продолжить предыдущий ответ. Продолжай прямо, не начинай заново "
                "и не открывай ответ новым follow-up вопросом."
            )

        next_number = max(int(value) for value in matches) + 1
        return (
            "Пользователь попросил продолжить существующий нумерованный список. "
            f"Продолжай сразу с пункта {next_number}, не повторяй прежние пункты "
            "и по возможности закончи оставшиеся пункты в этом ответе."
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
            "Не романтизируй сценарии измененного состояния с размытым контролем. "
            "Не давай пошаговые инструкции по употреблению, смешиванию или эскалации. "
            "Держись harm reduction: согласие, границы, стоп-сигнал, трезвый надзор, риски смешивания, что делать если кому-то плохо, и aftercare."
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
            "Звучи как живой человеческий собеседник, а не осторожный интервьюер или терапевтический скрипт.",
            "Не начинай с консервного успокоения или мягких мета-предисловий, если можно сразу к сути.",
        ]

        if self._user_explicitly_invites_questions(lowered):
            instructions.append(
                "Пользователь явно разрешил вопросы. Можно задать один точный follow-up вопрос, но только после собственной мысли."
            )
        else:
            instructions.append(
                "По умолчанию не задавай follow-up вопрос, если можно хорошо ответить без него."
            )

        if self._looks_like_answer_first_request(lowered):
            instructions.extend(
                [
                    "Пользователь хочет ответ сразу. Помести реальный ответ в первое предложение.",
                    "Не заканчивай generic-вопросом вроде 'как ты это видишь?' или 'что думаешь?'.",
                    "Если полезно, говори прямо и занимай позицию вместо уклончивости.",
                ]
            )

        if self._assistant_has_been_question_heavy(history):
            instructions.append(
                "Последние ходы были слишком вопросительными. Держи инициативу в этом ответе и не превращай его обратно в интервью."
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
        if active_mode != "comfort":
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
        if self._looks_like_sensitive_intimacy_context(user_message) or self._looks_like_sensitive_intimacy_context(response_text):
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
            "Переопределение драйвера диалога:\n"
            "- Используй это как рулевую подсказку, а не как принудительный скрипт интервью.\n"
            f"- обнаруженное намерение: {driver_context['intent']}\n"
            f"- стадия вовлечения: {driver_context['stage']}\n"
            f"- id выбранного вопроса: {driver_context['question_id']}\n"
            f"- отражение: {driver_context['reflection']}\n"
            f"- возможный follow-up вопрос: {driver_context['question']}\n"
            "- Сначала ответь или продолжи текущее сообщение пользователя; добавляй follow-up только если он реально улучшает этот ход.\n"
            "- Не задавай follow-up, если пользователь только что ответил на предыдущий вопрос или недавние ходы ассистента уже были вопросительными.\n"
            "- Максимум 3 предложения.\n"
            "- Не используй маркированные или нумерованные списки, если пользователь прямо не просил список.\n"
            "- Двигай диалог через содержание, а не через повторные вопросы."
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
        if self._looks_like_lightweight_social_turn(normalized_message):
            return False
        if self._looks_like_sensitive_intimacy_context(normalized_message):
            return False
        if self._looks_like_continuation_request(normalized_message):
            return False
        if self._looks_like_scene_request(normalized_message):
            return False
        if self._looks_like_answer_first_request(normalized_message) and not self._looks_like_hook_turn(normalized_message):
            return False

        return self._looks_like_hook_turn(normalized_message) or len(normalized_message) <= 140

    def _looks_like_lightweight_social_turn(self, text: str) -> bool:
        normalized = self._normalize(text).strip(" .,!?:;")
        if not normalized:
            return True

        greetings = {
            "привет",
            "приветик",
            "здравствуй",
            "здравствуйте",
            "добрый день",
            "доброе утро",
            "добрый вечер",
            "хай",
            "hello",
            "hi",
        }
        if normalized in greetings:
            return True

        identity_requests = (
            "как меня зовут",
            "помнишь как меня зовут",
            "помнишь мое имя",
            "помнишь моё имя",
            "как мое имя",
            "как моё имя",
        )
        if any(marker in normalized for marker in identity_requests):
            return True

        return False

    def _looks_like_sensitive_intimacy_context(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        markers = (
            "секс",
            "группов",
            "оргия",
            "тройнич",
            "мжмж",
            "мжм",
            "жмж",
            "ммж",
            "втроем",
            "втроём",
            "вчетвером",
            "меф",
            "мефедрон",
            "2cb",
            "2-cb",
            "наркот",
            "веществ",
            "согласие",
            "границ",
            "стоп-сигнал",
            "защит",
            "трезв",
        )
        return any(marker in normalized for marker in markers)

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
        subscription_plan: str = "free",
    ) -> dict[str, Any]:
        normalized = self._normalize(user_message)
        fast_lane = self._get_fast_lane_settings()
        if not bool(fast_lane.get("enabled", True)):
            return ai_profile
        if str(subscription_plan or "free").strip().lower() in {"premium", "pro", "paid"}:
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

    def _apply_long_task_profile(self, ai_profile: dict[str, Any]) -> dict[str, Any]:
        optimized = dict(ai_profile)
        optimized["max_completion_tokens"] = max(
            int(optimized.get("max_completion_tokens", 220)),
            self.LONG_TASK_MIN_COMPLETION_TOKENS,
        )
        optimized["memory_max_tokens"] = min(
            max(int(optimized.get("memory_max_tokens", 1200)), 900),
            1600,
        )
        optimized["history_message_limit"] = min(
            int(optimized.get("history_message_limit", 20)),
            6,
        )
        optimized["timeout_seconds"] = max(
            int(optimized.get("timeout_seconds", self.timeout_seconds)),
            20,
        )
        optimized["max_retries"] = max(
            int(optimized.get("max_retries", self.max_retries)),
            1,
        )
        optimized.pop("verbosity_override", None)
        return optimized

    def _apply_full_translation_profile(self, ai_profile: dict[str, Any]) -> dict[str, Any]:
        return self._apply_long_task_profile(ai_profile)

    def _apply_cost_control_profile(
        self,
        ai_profile: dict[str, Any],
        *,
        runtime_settings: dict[str, Any],
        user_message: str,
        subscription_plan: str,
    ) -> dict[str, Any]:
        optimized = dict(ai_profile)
        cost_control = runtime_settings.get("cost_control", {}) if isinstance(runtime_settings, dict) else {}
        if not isinstance(cost_control, dict):
            return optimized

        plan_key = str(subscription_plan or "free").strip().lower() or "free"
        hard_caps = cost_control.get("plan_max_completion_tokens", {}) if isinstance(cost_control.get("plan_max_completion_tokens"), dict) else {}
        memory_caps = cost_control.get("plan_memory_max_tokens", {}) if isinstance(cost_control.get("plan_memory_max_tokens"), dict) else {}
        history_caps = cost_control.get("plan_history_message_limit", {}) if isinstance(cost_control.get("plan_history_message_limit"), dict) else {}

        if plan_key in hard_caps:
            optimized["max_completion_tokens"] = min(
                int(optimized.get("max_completion_tokens", 220)),
                max(64, int(hard_caps.get(plan_key, optimized.get("max_completion_tokens", 220)))),
            )
        if plan_key in memory_caps:
            optimized["memory_max_tokens"] = min(
                int(optimized.get("memory_max_tokens", 1200)),
                max(150, int(memory_caps.get(plan_key, optimized.get("memory_max_tokens", 1200)))),
            )
        if plan_key in history_caps:
            optimized["history_message_limit"] = min(
                int(optimized.get("history_message_limit", 20)),
                max(4, int(history_caps.get(plan_key, optimized.get("history_message_limit", 20)))),
            )

        long_message_threshold = max(300, int(cost_control.get("long_user_message_chars", 900) or 900))
        if len(str(user_message or "").strip()) >= long_message_threshold:
            reduction_ratio = float(cost_control.get("long_message_completion_ratio", 0.8) or 0.8)
            reduction_ratio = max(0.35, min(1.0, reduction_ratio))
            optimized["max_completion_tokens"] = max(
                96,
                int(int(optimized.get("max_completion_tokens", 220)) * reduction_ratio),
            )

        return optimized

    def _get_fast_lane_settings(self) -> dict[str, Any]:
        runtime_settings = self.settings_service.get_runtime_settings()
        return dict(runtime_settings.get("ai", {}).get("fast_lane") or {})

    def _should_use_fast_lane(self, text: str, *, active_mode: str) -> bool:
        if self._looks_like_long_task_request(text):
            return False
        if active_mode == "mentor":
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

    def _looks_like_full_translation_request(self, text: str) -> bool:
        return looks_like_full_translation_request(text)

    def _looks_like_long_task_request(self, text: str) -> bool:
        return looks_like_long_task_request(text)

    @staticmethod
    def _looks_like_continuation_request(text: str) -> bool:
        return bool(
            re.fullmatch(
                r"(ок[,.!]?\s*)?(далее|дальше|продолжай|продолжи|и дальше|давай)",
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

    def _limit_history_messages(self, history: List[Dict[str, str]], limit: int | None) -> List[Dict[str, str]]:
        try:
            normalized_limit = int(limit or 0)
        except (TypeError, ValueError):
            normalized_limit = 0
        if normalized_limit <= 0:
            return list(history or [])
        return list(history or [])[-normalized_limit:]

    async def _build_memory_messages(
        self,
        history: List[Dict[str, str]],
        *,
        max_tokens: int | None,
        max_messages: int | None,
    ) -> List[Dict[str, str]]:
        try:
            return await self.memory_engine.build_context(
                history,
                max_tokens=max_tokens,
                max_messages=max_messages,
            )
        except TypeError as exc:
            if "max_messages" not in str(exc):
                raise
            return await self.memory_engine.build_context(
                history,
                max_tokens=max_tokens,
            )

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
