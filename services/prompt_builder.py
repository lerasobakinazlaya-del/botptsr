from core.mode_loader import get_mode_config
from core.mode_prompt_builder import build_mode_instruction


class PromptBuilder:
    def __init__(self, settings_service):
        self.settings_service = settings_service

    def build_system_prompt(
        self,
        state: dict,
        access_level: str,
        active_mode: str = "base",
        memory_context: str = "",
        user_message: str = "",
    ) -> str:
        templates = self.settings_service.get_prompt_templates()
        runtime_settings = self.settings_service.get_runtime_settings()
        ai_settings = runtime_settings["ai"]
        mode_config = get_mode_config(active_mode)
        mode_catalog = self.settings_service.get_mode_catalog().get(active_mode, {})
        mode_instruction = build_mode_instruction(mode_config)
        mode_description = self._build_mode_description(mode_catalog)
        access_rule = templates["access_rules"].get(
            access_level,
            templates["access_rules"]["observation"],
        )
        state_summary = self._build_state_summary(
            state=state,
            active_mode=active_mode,
            access_level=access_level,
        )
        response_contract = self._build_response_contract(
            user_message=user_message,
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            mode_config=mode_config,
        )
        language_instruction = self._build_language_instruction(
            ai_settings.get("response_language", "ru"),
        )

        parts = [
            templates["personality_core"],
            templates["safety_block"],
            templates.get("response_style", ""),
            templates.get("engagement_rules", ""),
            f"{templates['mode_intro']}\n{mode_instruction}",
            mode_description,
            f"{templates['access_intro']}\n{access_rule}",
        ]

        if memory_context.strip():
            parts.append(f"{templates['memory_intro']}\n{memory_context}")

        parts.append(f"{templates['state_intro']}\n{state_summary}")
        parts.append(response_contract)
        parts.append(language_instruction)
        parts.append(templates["final_instruction"])

        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    def _build_state_summary(
        self,
        state: dict,
        active_mode: str,
        access_level: str,
    ) -> str:
        keys = [
            "interest",
            "control",
            "attraction",
            "instability",
            "fatigue",
            "irritation",
            "conversation_phase",
            "interaction_count",
        ]

        lines = [
            f"- active_mode: {active_mode}",
            f"- access_level: {access_level}",
        ]

        for key in keys:
            if key in state:
                value = state[key]
                if isinstance(value, float):
                    value = round(value, 3)
                lines.append(f"- {key}: {value}")

        return "\n".join(lines)

    def _build_mode_description(self, mode_catalog: dict) -> str:
        if not mode_catalog:
            return ""

        lines = [
            f"Mode name: {mode_catalog.get('name', '')}",
            f"Mode description: {mode_catalog.get('description', '')}",
            f"Mode tone: {mode_catalog.get('tone', '')}",
            f"Emotional state: {mode_catalog.get('emotional_state', '')}",
            f"Behavior rules:\n{mode_catalog.get('behavior_rules', '')}",
        ]
        return "\n".join(line for line in lines if line.strip())

    def _build_response_contract(
        self,
        user_message: str,
        state: dict,
        access_level: str,
        active_mode: str,
        mode_config: dict,
    ) -> str:
        text = (user_message or "").strip()
        lowered = text.lower()
        message_length = len(text)
        fatigue = float(state.get("fatigue", 0.0) or 0.0)
        irritation = float(state.get("irritation", 0.0) or 0.0)
        warmth = int(mode_config.get("warmth", 5) or 5)
        depth = int(mode_config.get("depth", 5) or 5)
        structure = int(mode_config.get("structure", 5) or 5)
        dominance = int(mode_config.get("dominance", 5) or 5)
        initiative = int(mode_config.get("initiative", 5) or 5)
        flirt = int(mode_config.get("flirt", 0) or 0)
        emoji_level = int(mode_config.get("emoji_level", 0) or 0)

        lines = [
            "Response contract:",
            "- Stay in character, but optimize for usefulness, emotional precision, and natural flow.",
            "- Answer the user's actual point before you steer the conversation anywhere else.",
            "- Use memory naturally. Do not dump profile facts or sound like you are reading notes.",
            "- Ask at most one focused follow-up question unless the user explicitly asks for a deeper breakdown.",
        ]

        if "?" in text or self._looks_like_direct_question(lowered):
            lines.append("- There is a direct question. Answer it clearly in the first part of the reply.")

        if message_length <= 25 and "?" not in text:
            lines.append("- The user message is brief. Keep the reply compact, warm, and easy to continue.")
        elif message_length >= 280:
            lines.append("- The user gave a long message. Reflect the core emotion and meaning before offering guidance.")

        if fatigue >= 0.55 or irritation >= 0.45:
            lines.append("- The dialogue state suggests overload. Be calmer, shorter, and lower-pressure than usual.")

        if structure >= 7:
            lines.append("- Favor clean structure: short paragraphs, explicit transitions, and crisp logic.")
        elif structure <= 3:
            lines.append("- Favor a more fluid, conversational rhythm over rigid structure.")

        if depth >= 7:
            lines.append("- If the user is reflective, name the deeper subtext gently and offer one meaningful angle to explore.")

        if initiative >= 7:
            lines.append("- If the user is vague or stuck, move the conversation forward with one concrete next step or choice.")

        if warmth >= 8:
            lines.append("- Let warmth be obvious in the wording, but keep it grounded and never cloying.")

        if flirt >= 6:
            lines.append("- If intimacy fits the moment, keep it subtle, tasteful, and responsive to the user's lead.")
        elif access_level in {"observation", "analysis"}:
            lines.append("- Keep closeness restrained; do not intensify intimacy ahead of the user's signal.")

        if dominance >= 7:
            lines.append("- Sound composed and leading, but never harsh, humiliating, or coercive.")

        lines.append(self._build_emoji_rule(emoji_level))
        lines.append(f"- Active mode is '{active_mode}'. Honor its tone without turning the reply into a caricature.")

        return "\n".join(line for line in lines if line.strip())

    def _build_language_instruction(self, response_language: str) -> str:
        language = (response_language or "ru").strip() or "ru"
        return (
            "Language rule:\n"
            f"- Reply in {language} by default.\n"
            "- If the user clearly switches language, you may mirror them."
        )

    def _build_emoji_rule(self, emoji_level: int) -> str:
        if emoji_level <= 0:
            return "- Do not use emoji."
        if emoji_level == 1:
            return "- Avoid emoji unless one tiny signal feels truly natural."
        if emoji_level == 2:
            return "- Use at most one light emoji when it adds warmth without noise."
        return "- Use emoji sparingly, never more than two, and only if they genuinely fit the mood."

    def _looks_like_direct_question(self, text: str) -> bool:
        question_starts = (
            "why ",
            "how ",
            "what ",
            "when ",
            "where ",
            "who ",
            "which ",
            "can you ",
            "could you ",
            "should i ",
            "стоит ли",
            "почему",
            "как ",
            "что ",
            "зачем",
            "когда",
            "где",
            "кто",
            "можешь",
            "подскажи",
        )
        return text.startswith(question_starts)
