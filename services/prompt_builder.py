from __future__ import annotations

from services.conversation_engine_v2 import ConversationEngineV2


class PromptBuilder:
    """
    Compatibility adapter.

    Runtime generation now goes through ConversationEngineV2 so chat,
    reengagement, and proactive flows share one prompt compiler.
    """

    def __init__(self, settings_service, conversation_engine: ConversationEngineV2 | None = None):
        self.settings_service = settings_service
        self.conversation_engine = conversation_engine or ConversationEngineV2(settings_service)

    def build_system_prompt(
        self,
        state: dict,
        access_level: str,
        active_mode: str = "base",
        memory_context: str = "",
        user_message: str = "",
        extra_instruction: str = "",
        base_instruction: str = "",
        history: list | None = None,
        is_reengagement: bool = False,
        is_proactive: bool = False,
        access_profile: dict | None = None,
    ) -> str:
        return self.conversation_engine.build_system_prompt(
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            memory_context=memory_context,
            user_message=user_message,
            base_instruction=base_instruction or extra_instruction,
            history=history or [],
            is_reengagement=is_reengagement,
            is_proactive=is_proactive,
            access_profile=access_profile,
        )
