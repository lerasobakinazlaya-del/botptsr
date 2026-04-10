from __future__ import annotations

from core.mode_loader import get_mode_config
from core.mode_prompt_builder import build_mode_instruction
from services.prompt_builder import PromptBuilder
from services.prompt_safety import sanitize_untrusted_context


class PromptBuilderV2(PromptBuilder):
    def build_system_prompt(
        self,
        state: dict,
        access_level: str,
        active_mode: str = "base",
        memory_context: str = "",
        user_message: str = "",
        extra_instruction: str = "",
        intent_snapshot: dict | None = None,
    ) -> str:
        templates = self.settings_service.get_prompt_templates()
        runtime_settings = self.settings_service.get_runtime_settings()
        ai_settings = runtime_settings["ai"]
        mode_config = get_mode_config(active_mode)
        mode_instruction = build_mode_instruction(mode_config)
        mode_signature = self._build_mode_signature(
            active_mode=active_mode,
            emotional_tone=str(state.get("emotional_tone") or "neutral"),
            access_level=access_level,
            user_message=user_message,
        )
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
            intent_snapshot=intent_snapshot,
        )
        language_instruction = self._build_language_instruction(
            ai_settings.get("response_language", "ru"),
        )
        safe_memory_context = sanitize_untrusted_context(memory_context)
        intent_snapshot = intent_snapshot or {}

        parts = [
            templates["personality_core"],
            templates["safety_block"],
            templates.get("response_style", ""),
            templates.get("engagement_rules", ""),
            f"{templates['mode_intro']}\n{mode_instruction}",
            mode_signature,
            f"{templates['access_intro']}\n{access_rule}",
        ]

        if safe_memory_context and bool(intent_snapshot.get("use_memory", True)):
            parts.append(
                f"{templates['memory_intro']}\n{self._build_untrusted_memory_block(safe_memory_context)}"
            )

        parts.append(
            self._build_intent_block(
                intent_snapshot=intent_snapshot,
                user_message=user_message,
            )
        )

        effective_mode = "ptsd" if active_mode == "comfort" else active_mode

        if effective_mode in {"free_talk", "ptsd"} and templates.get("ptsd_mode_prompt", "").strip():
            parts.append(templates["ptsd_mode_prompt"])

        parts.append(f"{templates['state_intro']}\n{state_summary}")
        parts.append(response_contract)
        parts.append(language_instruction)
        if extra_instruction.strip():
            parts.append(extra_instruction.strip())
        parts.append(templates["final_instruction"])

        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    def _build_intent_block(
        self,
        *,
        intent_snapshot: dict,
        user_message: str,
    ) -> str:
        intent = str(intent_snapshot.get("intent") or "discussion")
        desired_length = str(intent_snapshot.get("desired_length") or "medium")
        needs_clarification = bool(intent_snapshot.get("needs_clarification"))
        should_end_with_question = bool(intent_snapshot.get("should_end_with_question"))

        lines = [
            "Фокус текущего ответа:",
            f"- Тип запроса: {intent}.",
            f"- Предпочтительная длина: {desired_length}.",
        ]
        if "?" in (user_message or ""):
            lines.append("- У пользователя прямой вопрос: ответь по существу уже в начале.")
        if needs_clarification:
            lines.append("- Уточняй только если без этого ответ получится слишком расплывчатым.")
        else:
            lines.append("- Не уводи разговор в лишние уточнения, если уже можно помочь по делу.")
        if should_end_with_question:
            lines.append("- Один мягкий вопрос в конце допустим, если он реально поддерживает диалог.")
        else:
            lines.append("- Не обязательно заканчивать вопросом: цельная реплика лучше формального follow-up.")
        return "\n".join(lines)

    def _build_response_contract(
        self,
        *,
        user_message: str,
        state: dict,
        access_level: str,
        active_mode: str,
        mode_config: dict,
        intent_snapshot: dict | None = None,
    ) -> str:
        base_contract = super()._build_response_contract(
            user_message=user_message,
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            mode_config=mode_config,
        )
        intent_snapshot = intent_snapshot or {}
        desired_length = str(intent_snapshot.get("desired_length") or "medium")
        intent = str(intent_snapshot.get("intent") or "discussion")
        needs_clarification = bool(intent_snapshot.get("needs_clarification"))

        additions: list[str] = []
        if intent == "direct_answer":
            additions.append("- На прямой вопрос отвечай по делу уже в первых строках, без долгого захода.")
        elif intent == "support":
            additions.append("- Если человеку тяжело, сначала дай опору и ощущение контакта, потом уже предлагай рамку или шаг.")
        elif intent == "smalltalk":
            additions.append("- В small talk лучше лёгкий естественный ритм, чем слишком серьёзный разбор.")
        elif intent == "flirty":
            additions.append("- Флирт должен оставаться деликатным, взрослым и добровольным, без форсирования близости.")
        elif intent == "reengagement":
            additions.append("- Это инициирующее сообщение после паузы: звучишь легко, ненавязчиво и без давления.")

        if desired_length == "brief":
            additions.append("- Предпочти короткую реплику без лишних пояснений и без повторов одной мысли.")
        elif desired_length == "detailed":
            additions.append("- Можно развернуть мысль глубже обычного, но сохраняй фокус на одном основном направлении.")

        if needs_clarification:
            additions.append("- Если уточнение действительно нужно, задай только один точный вопрос вместо серии вопросов.")

        if not additions:
            return base_contract
        return "\n".join([base_contract, *additions])
