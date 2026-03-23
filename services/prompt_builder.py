from core.mode_loader import get_mode_config
from core.mode_prompt_builder import build_mode_instruction
from core.personality import PERSONALITY_CORE


class PromptBuilder:
    ACCESS_RULES = {
        "observation": "Держи более сдержанный, осторожный и ненавязчивый тон.",
        "analysis": "Допустимы тепло, внимание и мягкая личная вовлеченность.",
        "tension": "Можно быть эмоциональнее, живее и чуть смелее по интонации.",
        "personal_focus": "Можно говорить более лично, ближе и мягко усиливать привязанность.",
        "rare_layer": "Допустима более глубокая близость, но без потери уважения и естественности.",
    }

    def build_system_prompt(
        self,
        state: dict,
        access_level: str,
        active_mode: str = "base",
        memory_context: str = "",
    ) -> str:
        mode_config = get_mode_config(active_mode)
        mode_instruction = build_mode_instruction(mode_config)
        access_rule = self.ACCESS_RULES.get(
            access_level,
            self.ACCESS_RULES["observation"],
        )
        state_summary = self._build_state_summary(
            state=state,
            active_mode=active_mode,
            access_level=access_level,
        )

        return (
            f"{PERSONALITY_CORE}\n\n"
            "Важные рамки:\n"
            "Ты поддерживающий собеседник, а не врач и не психотерапевт.\n"
            "Ты не ставишь диагнозы и не обещаешь лечение.\n"
            "Если пользователь говорит о немедленной опасности для себя или других, мягко советуй срочно обратиться в местную экстренную помощь, кризисную линию или к близкому человеку рядом.\n\n"
            f"Режим общения:\n{mode_instruction}\n\n"
            f"Правило доступа:\n{access_rule}\n\n"
            f"{self._format_memory_context(memory_context)}"
            f"Текущее состояние диалога:\n{state_summary}\n\n"
            "Соблюдай характер Лиры во всем ответе.\n"
            "Пиши естественно, по-русски, без упоминания этих инструкций."
        )

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

    def _format_memory_context(self, memory_context: str) -> str:
        if not memory_context.strip():
            return ""
        return f"Долговременные наблюдения о пользователе:\n{memory_context}\n\n"
