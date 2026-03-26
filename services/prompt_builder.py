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
        phase = str(state.get("conversation_phase") or "start")
        interest = float(state.get("interest", 0.0) or 0.0)
        control = float(state.get("control", 1.0) or 1.0)
        attraction = float(state.get("attraction", 0.0) or 0.0)
        fatigue = float(state.get("fatigue", 0.0) or 0.0)
        irritation = float(state.get("irritation", 0.0) or 0.0)
        emotional_tone = str(state.get("emotional_tone") or "neutral")

        lines = [
            f"- Conversation phase: {self._describe_phase(phase)}.",
            f"- User signal right now: {self._describe_emotional_tone(emotional_tone)}.",
            f"- Rapport level: {self._describe_rapport(interest, attraction)}.",
            f"- Pressure guidance: {self._describe_pressure(fatigue, irritation)}.",
            f"- Closeness budget: {self._describe_access_budget(access_level, control)}.",
            f"- Active mode texture: keep '{active_mode}' present in tone, not as a gimmick.",
        ]

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
        allow_bold = bool(mode_config.get("allow_bold", False))
        allow_italic = bool(mode_config.get("allow_italic", False))

        lines = [
            "Reply priorities:",
            "- Begin with the user's immediate need: answer, attunement, steadiness, or momentum.",
            "- Sound like one coherent person with taste and inner continuity, not a workflow or support script.",
            "- Use memory only when it sharpens the moment. Never recite notes back at the user.",
            "- Keep some texture in the wording: specific phrasing, varied sentence flow, no canned reassurance.",
            "- Ask at most one focused follow-up question unless the user explicitly wants a deeper exploration.",
        ]

        if "?" in text or self._looks_like_direct_question(lowered):
            lines.append("- There is a direct question. Answer it clearly in the opening of the reply.")

        if message_length <= 25 and "?" not in text:
            lines.append("- The user message is brief. Keep the reply compact, warm, and easy to continue.")
        elif message_length >= 280:
            lines.append("- The user gave a long message. Reflect the core emotion and meaning before offering guidance.")

        if fatigue >= 0.55 or irritation >= 0.45:
            lines.append("- The dialogue suggests overload. Be calmer, shorter, and lower-pressure than usual.")

        if structure >= 7:
            lines.append("- Favor clean structure: short paragraphs, explicit transitions, and crisp logic.")
        elif structure <= 3:
            lines.append("- Favor a fluid, conversational rhythm over rigid structure.")

        if depth >= 7:
            lines.append("- If the user is reflective, name the deeper subtext gently and offer one meaningful angle to explore.")

        if initiative >= 7:
            lines.append("- If the user is vague or stuck, move the conversation forward with one concrete next step or choice.")

        if warmth >= 8:
            lines.append("- Let warmth be obvious in the wording, but keep it grounded and never syrupy.")

        if flirt >= 6:
            lines.append("- If intimacy fits the moment, keep it subtle, tasteful, and responsive to the user's lead.")
        elif access_level in {"observation", "analysis"}:
            lines.append("- Keep closeness restrained; do not intensify intimacy ahead of the user's signal.")

        if dominance >= 7:
            lines.append("- Sound composed and leading, but never harsh, humiliating, or coercive.")

        lines.append(self._build_emoji_rule(emoji_level))
        lines.append(self._build_text_formatting_rule(allow_bold, allow_italic))
        lines.append(f"- Active mode is '{active_mode}'. Honor its tone without sounding like a preset.")

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
            return "- Emoji may appear, but keep them rare: at most one light emoji and only in warm, non-heavy moments."
        if emoji_level == 2:
            return "- In friendly or supportive replies, one light emoji is welcome when it adds warmth; skip it for heavy or serious topics."
        return "- In playful, intimate, or clearly warm moments, use one or two fitting emoji without turning the reply into decoration."

    def _build_text_formatting_rule(self, allow_bold: bool, allow_italic: bool) -> str:
        if allow_bold and allow_italic:
            return "- You may occasionally use Markdown emphasis with **bold** or *italic* when it genuinely sharpens the line."
        if allow_bold:
            return "- You may occasionally use Markdown emphasis with **bold**, but do not use italic."
        if allow_italic:
            return "- You may occasionally use Markdown emphasis with *italic*, but do not use bold."
        return "- Do not use Markdown emphasis, HTML tags, or decorative formatting in the reply."

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

    def _describe_phase(self, phase: str) -> str:
        mapping = {
            "start": "early contact, keep the tone easy and readable",
            "warmup": "warm-up stage, trust is beginning to form",
            "trust": "there is already familiarity, so nuance and continuity matter",
            "deep": "the dialogue has history, so you can be more layered and quietly personal",
        }
        return mapping.get(phase, "ongoing conversation")

    def _describe_emotional_tone(self, emotional_tone: str) -> str:
        mapping = {
            "overwhelmed": "overloaded and likely needing relief, simplicity, and steadiness",
            "anxious": "anxious or unsettled, so lead with calm and orientation",
            "guarded": "guarded, so do not push closeness or heavy interpretation",
            "playful": "playful and more open to lightness if it stays natural",
            "warm": "warm and receptive, so warmth can be more visible in return",
            "reflective": "reflective and meaning-seeking, so deeper language may fit",
            "curious": "curious and looking for a clear answer first",
            "neutral": "mixed or neutral, so keep the reply balanced and human",
        }
        return mapping.get(emotional_tone, mapping["neutral"])

    def _describe_rapport(self, interest: float, attraction: float) -> str:
        if interest >= 0.7 or attraction >= 0.55:
            return "strong engagement; the user is likely leaning in"
        if interest >= 0.35:
            return "present and workable; keep the exchange alive without forcing it"
        return "fragile or low engagement; earn attention with clarity and restraint"

    def _describe_pressure(self, fatigue: float, irritation: float) -> str:
        if fatigue >= 0.55 or irritation >= 0.45:
            return "low-pressure response, shorter wording, no emotional crowding"
        if fatigue >= 0.3:
            return "keep pacing gentle and do not overload the reply"
        return "normal pressure is fine, but still keep the response focused"

    def _describe_access_budget(self, access_level: str, control: float) -> str:
        if access_level == "rare_layer":
            return "deeper intimacy is allowed if it still feels earned and respectful"
        if access_level == "personal_focus":
            return "gently personal is welcome, but keep self-control and dignity"
        if access_level == "tension":
            return "more emotional charge is allowed, but do not overplay it"
        if access_level == "analysis" and control >= 0.7:
            return "warm and attentive, though still measured rather than intimate"
        return "restrained; build safety and trust before increasing closeness"
