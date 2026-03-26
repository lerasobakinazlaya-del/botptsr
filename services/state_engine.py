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

    def __init__(self, settings_service=None):
        self.settings_service = settings_service

    def update_state(self, state: dict, user_message: str) -> dict:
        config = self._get_config()
        effects = config["message_effects"]
        current_state = self._with_defaults(state, config["defaults"])
        message = (user_message or "").strip()
        message_len = len(message)
        lowered = message.lower()

        if message_len > int(effects["long_message_threshold"]):
            current_state["interest"] += effects["long_interest_bonus"]
            current_state["attraction"] += effects["long_attraction_bonus"]
            current_state["control"] -= effects["long_control_penalty"]
        elif message_len > int(effects["medium_message_threshold"]):
            current_state["interest"] += effects["medium_interest_bonus"]
        elif message_len < int(effects["short_message_threshold"]):
            current_state["interest"] -= effects["short_interest_penalty"]

        if "?" in message:
            current_state["interest"] += effects["question_interest_bonus"]

        if any(word in lowered for word in config["positive_keywords"]):
            current_state["attraction"] += effects["positive_attraction_bonus"]
            current_state["control"] -= effects["positive_control_penalty"]

        if any(word in lowered for word in config["negative_keywords"]):
            current_state["irritation"] += effects["negative_irritation_bonus"]
            current_state["interest"] -= effects["negative_interest_penalty"]

        if any(word in lowered for word in config["attraction_keywords"]):
            current_state["attraction"] += effects["attraction_bonus"]
            current_state["interest"] += effects["attraction_interest_bonus"]
            current_state["control"] -= effects["attraction_control_penalty"]

        current_state["fatigue"] += effects["fatigue_per_message"]
        current_state["instability"] += (
            current_state["attraction"] - current_state["control"]
        ) * effects["instability_factor"]

        if current_state["attraction"] > effects["high_attraction_threshold"]:
            current_state["control"] -= effects["high_attraction_control_penalty"]

        current_state["interaction_count"] = int(current_state.get("interaction_count", 0)) + 1
        current_state["conversation_phase"] = self._derive_phase(current_state["interaction_count"])

        return self._clamp_numeric_values(current_state)

    def _get_config(self) -> dict:
        if self.settings_service is None:
            return {
                "defaults": self.DEFAULTS,
                "positive_keywords": ["спасибо", "ценю", "приятно", "нежно"],
                "negative_keywords": ["злишь", "бесишь", "отстань", "хватит"],
                "attraction_keywords": ["люблю", "скучаю", "хочу тебя", "близко"],
                "message_effects": {
                    "long_message_threshold": 300,
                    "medium_message_threshold": 120,
                    "short_message_threshold": 30,
                    "long_interest_bonus": 0.07,
                    "long_attraction_bonus": 0.03,
                    "long_control_penalty": 0.01,
                    "medium_interest_bonus": 0.04,
                    "short_interest_penalty": 0.03,
                    "question_interest_bonus": 0.02,
                    "positive_attraction_bonus": 0.03,
                    "positive_control_penalty": 0.01,
                    "negative_irritation_bonus": 0.08,
                    "negative_interest_penalty": 0.04,
                    "attraction_bonus": 0.06,
                    "attraction_interest_bonus": 0.03,
                    "attraction_control_penalty": 0.03,
                    "fatigue_per_message": 0.01,
                    "instability_factor": 0.02,
                    "high_attraction_threshold": 0.5,
                    "high_attraction_control_penalty": 0.02,
                },
            }

        runtime = self.settings_service.get_runtime_settings()
        return runtime["state_engine"]

    def _with_defaults(self, state: dict | None, defaults: dict) -> dict:
        current_state = (state or {}).copy()
        for key, value in defaults.items():
            current_state.setdefault(key, value)
        current_state.setdefault("interaction_count", 0)
        current_state.setdefault("conversation_phase", "start")
        current_state.setdefault("active_mode", "base")
        return current_state

    def _derive_phase(self, interaction_count: int) -> str:
        if interaction_count >= 20:
            return "deep"
        if interaction_count >= 8:
            return "trust"
        if interaction_count >= 3:
            return "warmup"
        return "start"

    def _clamp_numeric_values(self, state: dict) -> dict:
        for key, value in state.items():
            if key == "interaction_count":
                state[key] = max(0, int(value))
            elif isinstance(value, (int, float)):
                state[key] = max(0.0, min(1.0, value))
        return state
