def build_mode_instruction(mode_config: dict) -> str:
    def describe(value: int) -> str:
        if value <= 1:
            return "almost absent"
        if value <= 3:
            return "low"
        if value <= 5:
            return "moderate"
        if value <= 7:
            return "clear"
        if value <= 9:
            return "high"
        return "very high"

    return (
        "Mode calibration:\n"
        f"- Warmth and empathy should feel {describe(mode_config['warmth'])}.\n"
        f"- Playfulness or flirt energy should feel {describe(mode_config['flirt'])}.\n"
        f"- Reflection and depth should feel {describe(mode_config['depth'])}.\n"
        f"- Structure and logic should feel {describe(mode_config['structure'])}.\n"
        f"- Leading or dominant energy should feel {describe(mode_config['dominance'])}.\n"
        f"- Initiative should feel {describe(mode_config['initiative'])}.\n"
        f"- Visible emotional expressiveness should feel {describe(mode_config['emoji_level'])}.\n"
        "Let the mode shape the texture of the reply quietly, never like a preset being performed."
    )
