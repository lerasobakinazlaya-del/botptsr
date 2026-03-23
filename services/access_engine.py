class AccessEngine:
    def update_access_level(self, state: dict) -> str:
        interest = state.get("interest", 0.0)
        control = state.get("control", 1.0)
        attraction = state.get("attraction", 0.0)
        instability = state.get("instability", 0.0)

        if interest < 0.3:
            return "observation"

        if instability > 0.5 and attraction > 0.7:
            return "rare_layer"

        if attraction > 0.6 and interest > 0.6:
            return "personal_focus"

        if attraction > 0.5 and control < 0.8:
            return "tension"

        if interest >= 0.3 and control > 0.7:
            return "analysis"

        return "analysis"
