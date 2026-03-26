class AccessEngine:
    def __init__(self, settings_service=None):
        self.settings_service = settings_service

    def update_access_level(self, state: dict) -> str:
        config = self._get_config()
        forced_level = str(config.get("forced_level") or "").strip()
        if forced_level in {
            "observation",
            "analysis",
            "tension",
            "personal_focus",
            "rare_layer",
        }:
            return forced_level

        interest = state.get("interest", 0.0)
        control = state.get("control", 1.0)
        attraction = state.get("attraction", 0.0)
        instability = state.get("instability", 0.0)

        if interest < config["interest_observation_threshold"]:
            return "observation"

        if (
            instability > config["rare_layer_instability_threshold"]
            and attraction > config["rare_layer_attraction_threshold"]
        ):
            return "rare_layer"

        if (
            attraction > config["personal_focus_attraction_threshold"]
            and interest > config["personal_focus_interest_threshold"]
        ):
            return "personal_focus"

        if (
            attraction > config["tension_attraction_threshold"]
            and control < config["tension_control_threshold"]
        ):
            return "tension"

        if (
            interest >= config["analysis_interest_threshold"]
            and control > config["analysis_control_threshold"]
        ):
            return "analysis"

        return str(config.get("default_level") or "analysis")

    def _get_config(self) -> dict:
        if self.settings_service is None:
            return {
                "forced_level": "",
                "default_level": "analysis",
                "interest_observation_threshold": 0.3,
                "rare_layer_instability_threshold": 0.5,
                "rare_layer_attraction_threshold": 0.7,
                "personal_focus_attraction_threshold": 0.6,
                "personal_focus_interest_threshold": 0.6,
                "tension_attraction_threshold": 0.5,
                "tension_control_threshold": 0.8,
                "analysis_interest_threshold": 0.3,
                "analysis_control_threshold": 0.7,
            }

        return self.settings_service.get_runtime_settings()["access"]
