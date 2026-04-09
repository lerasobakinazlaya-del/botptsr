from services.intent_router import IntentRouter
from services.response_postprocessor import ResponsePostprocessor
from services.ai_service import AIService


class AIServiceV2(AIService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.intent_router = IntentRouter()
        self.postprocessor = ResponsePostprocessor()

    async def _generate_response_impl(self, history, user_message, state, user_id):
        intent_snapshot = self.intent_router.classify(
            user_message=user_message,
            state=state,
            history=history,
            active_mode=str(state.get("active_mode") or "base"),
        )

        result = await super()._generate_response_impl(
            history=history,
            user_message=user_message,
            state=state,
            user_id=user_id,
        )

        processed = self.postprocessor.postprocess(
            result.response,
            intent_snapshot=intent_snapshot,
            active_mode=str(state.get("active_mode") or "base"),
            state=state,
        )

        return type(result)(
            response=processed,
            new_state=result.new_state,
            tokens_used=result.tokens_used,
        )
