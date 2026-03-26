import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List


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


class AIBackpressureError(RuntimeError):
    pass


class AIService:
    EMPTY_RESPONSE_FALLBACK = (
        "Я рядом. Попробуй написать это чуть иначе, и я отвечу точнее."
    )

    def __init__(
        self,
        client,
        state_engine,
        memory_engine,
        keyword_memory_service,
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
    ):
        self.client = client
        self.state_engine = state_engine
        self.memory_engine = memory_engine
        self.keyword_memory_service = keyword_memory_service
        self.prompt_builder = prompt_builder
        self.access_engine = access_engine
        self.settings_service = settings_service
        self.debug = debug
        self.log_full_prompt = log_full_prompt
        self.debug_prompt_user_id = debug_prompt_user_id

        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_parallel_requests = max_parallel_requests

        self._queue: asyncio.Queue[AIRequest | None] = asyncio.Queue(maxsize=queue_size)
        self._workers: list[asyncio.Task] = []
        self._started = False

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

    def get_runtime_stats(self) -> dict[str, int | bool]:
        return {
            "started": self._started,
            "queue_size": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "workers": len(self._workers),
            "max_parallel_requests": self.max_parallel_requests,
        }

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
            raise AIBackpressureError("AI request queue is full")

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request = AIRequest(
            history=history,
            user_message=user_message,
            state=state,
            user_id=user_id,
            future=future,
        )
        self._queue.put_nowait(request)
        return await future

    async def _worker(self) -> None:
        while True:
            request = await self._queue.get()

            if request is None:
                self._queue.task_done()
                return

            try:
                result = await self._generate_response_impl(
                    history=request.history,
                    user_message=request.user_message,
                    state=request.state,
                    user_id=request.user_id,
                )
                if not request.future.done():
                    request.future.set_result(result)
            except Exception as exc:
                if not request.future.done():
                    request.future.set_exception(exc)
            finally:
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
        self.memory_engine.set_max_tokens(ai_settings["memory_max_tokens"])

        memory_enriched_state = self.keyword_memory_service.apply(state.copy(), user_message)
        new_state = self.state_engine.update_state(memory_enriched_state, user_message)
        active_mode = new_state.get("active_mode", "base")
        access_level = self.access_engine.update_access_level(new_state)
        memory_messages = await self.memory_engine.build_context(history)
        memory_context = self.keyword_memory_service.build_prompt_context(
            new_state,
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
        )

        if self._should_log_full_prompt(user_id, ai_settings):
            logger.debug("[AI PROMPT] user_id=%s\n%s", user_id, system_prompt)

        if grounding_kind is not None:
            logger.info("[AI] user_id=%s grounding=%s", user_id, grounding_kind)
            return AIResult(
                response=self.keyword_memory_service.build_grounding_response(grounding_kind),
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
            ai_settings,
            user_id=user_id,
        )
        if not response_text.strip():
            logger.warning("[AI] Empty response from model, using fallback")
            response_text = self.EMPTY_RESPONSE_FALLBACK

        return AIResult(
            response=response_text,
            new_state=new_state,
            tokens_used=tokens_used,
        )

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
        ai_settings: dict[str, Any],
        user_id: int,
    ) -> tuple[str, int | None]:
        last_exception = None
        max_retries = int(ai_settings.get("max_retries", self.max_retries))
        timeout_seconds = int(ai_settings.get("timeout_seconds", self.timeout_seconds))
        model = str(ai_settings.get("openai_model") or self.client.model)
        temperature = float(ai_settings.get("temperature", self.client.temperature))
        top_p = float(ai_settings.get("top_p", 1.0))
        frequency_penalty = float(ai_settings.get("frequency_penalty", 0.0))
        presence_penalty = float(ai_settings.get("presence_penalty", 0.0))
        max_completion_tokens = int(
            ai_settings.get("max_completion_tokens", 400),
        )
        reasoning_effort = str(ai_settings.get("reasoning_effort") or "").strip() or None
        verbosity = str(ai_settings.get("verbosity") or "").strip() or None

        for attempt in range(max_retries + 1):
            try:
                return await asyncio.wait_for(
                    self.client.generate(
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
            except asyncio.TimeoutError as exc:
                last_exception = exc
            except Exception as exc:
                last_exception = exc

            await asyncio.sleep(0.5 * (attempt + 1))

        raise RuntimeError("AI call failed after retries") from last_exception
