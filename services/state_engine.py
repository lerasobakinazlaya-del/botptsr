class StateEngine:
    DEFAULTS = {
        "coldness": 0.7,
        "interest": 0.4,
        "control": 0.9,
        "irritation": 0.0,
        "attraction": 0.1,
        "instability": 0.1,
        "fatigue": 0.0,
    }

    def update_state(self, state: dict, user_message: str) -> dict:
        current_state = self._with_defaults(state)
        message = user_message.strip()
        message_len = len(message)
        lowered = message.lower()

        if message_len > 300:
            current_state["interest"] += 0.07
            current_state["attraction"] += 0.03
            current_state["control"] -= 0.01
        elif message_len > 120:
            current_state["interest"] += 0.04
        elif message_len < 30:
            current_state["interest"] -= 0.03

        if "?" in message:
            current_state["interest"] += 0.02

        if any(word in lowered for word in ["спасибо", "ценю", "приятно", "нежно"]):
            current_state["attraction"] += 0.03
            current_state["control"] -= 0.01

        if any(word in lowered for word in ["злишь", "бесишь", "отстань", "хватит"]):
            current_state["irritation"] += 0.08
            current_state["interest"] -= 0.04

        if any(word in lowered for word in ["люблю", "скучаю", "хочу тебя", "близко"]):
            current_state["attraction"] += 0.06
            current_state["interest"] += 0.03
            current_state["control"] -= 0.03

        current_state["fatigue"] += 0.01
        current_state["instability"] += (current_state["attraction"] - current_state["control"]) * 0.02

        if current_state["attraction"] > 0.5:
            current_state["control"] -= 0.02

        return self._clamp_numeric_values(current_state)

    def _with_defaults(self, state: dict | None) -> dict:
        current_state = (state or {}).copy()
        for key, value in self.DEFAULTS.items():
            current_state.setdefault(key, value)
        return current_state

    def _clamp_numeric_values(self, state: dict) -> dict:
        for key, value in state.items():
            if isinstance(value, (int, float)):
                state[key] = max(0.0, min(1.0, value))
        return state
