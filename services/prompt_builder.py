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
    ) -> str:
        templates = self.settings_service.get_prompt_templates()
        mode_config = get_mode_config(active_mode)
        mode_instruction = build_mode_instruction(mode_config)
        access_rule = templates["access_rules"].get(
            access_level,
            templates["access_rules"]["observation"],
        )
        state_summary = self._build_state_summary(
            state=state,
            active_mode=active_mode,
            access_level=access_level,
        )

        parts = [
            templates["personality_core"],
            templates["safety_block"],
            f"{templates['mode_intro']}\n{mode_instruction}",
            f"{templates['access_intro']}\n{access_rule}",
        ]

        if memory_context.strip():
            parts.append(f"{templates['memory_intro']}\n{memory_context}")

        parts.append(f"{templates['state_intro']}\n{state_summary}")
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
