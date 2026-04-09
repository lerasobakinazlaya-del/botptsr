from __future__ import annotations

import logging
from typing import Any

from services.ai_service import AIService
from services.intent_router import IntentRouter
from services.response_postprocessor import ResponsePostprocessor


logger = logging.getLogger(__name__)


class AIServiceV2(AIService):
    def __init__(
        self,
        *args,
        intent_router: IntentRouter | None = None,
        response_postprocessor: ResponsePostprocessor | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.intent_router = intent_router or IntentRouter()
        self.response_postprocessor = response_postprocessor or ResponsePostprocessor()

    def _build_intent_snapshot(
        self,
        *,
        user_message: str,
        state: dict[str, Any],
        history: list[dict[str, str]],
        active_mode: str,
        source: str,
    ) -> dict[str, Any] | None:
        if source == "reengagement":
            snapshot = self.intent_router.classify(
                user_message=user_message or "",
                state=state,
                history=history,
                active_mode=active_mode,
            )
            snapshot.update(
                {
                    "intent": "reengagement",
                    "desired_length": "brief",
                    "needs_clarification": False,
                    "should_end_with_question": True,
                    "use_memory": True,
                }
            )
            return snapshot

        snapshot = self.intent_router.classify(
            user_message=user_message,
            state=state,
            history=history,
            active_mode=active_mode,
        )
        logger.debug(
            "[AI V2] source=%s intent=%s desired_length=%s use_memory=%s",
            source,
            snapshot.get("intent"),
            snapshot.get("desired_length"),
            snapshot.get("use_memory"),
        )
        return snapshot

    def _postprocess_model_response(
        self,
        response_text: str,
        *,
        intent_snapshot: dict[str, Any] | None,
        active_mode: str,
        state: dict[str, Any],
        source: str,
    ) -> str:
        return self.response_postprocessor.postprocess(
            response_text,
            intent_snapshot=intent_snapshot,
            active_mode=active_mode,
            state=state,
        )
