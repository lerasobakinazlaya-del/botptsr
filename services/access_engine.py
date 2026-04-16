from __future__ import annotations


class AccessEngine:
    VALID_ACCESS_LEVELS = {"observation", "analysis", "tension", "personal_focus", "rare_layer"}
    INTIMATE_MODE_LEVELS = {
        "passion": "personal_focus",
        "night": "tension",
        "dominant": "tension",
    }
    HEAVY_EMOTIONAL_TONES = {"overwhelmed", "anxious", "guarded"}
    NEGATIVE_INTIMACY_MARKERS = (
        "не флиртуй",
        "без флирта",
        "не дави",
        "не хочу близости",
        "не хочу этого",
        "не надо так",
        "не будь пошлой",
        "без пошлости",
        "don't flirt",
        "no flirting",
    )
    EXPLICIT_INTIMACY_MARKERS = (
        "хочу тебя",
        "будь ближе",
        "можешь быть ближе",
        "можешь быть смелее",
        "флиртуй",
        "заигрывай",
        "обними меня",
        "поцелуй",
        "эрот",
        "секс",
        "сексу",
        "желание",
        "возбуж",
        "веди меня",
        "скажи жестче",
        "be closer",
        "flirt with me",
        "kiss me",
        "turn me on",
        "be more dominant",
    )
    LEVEL_BUDGETS = {
        "observation": {
            "closeness": 0.18,
            "sexual_tension": 0.00,
            "explicitness": 0.00,
            "dominance": 0.16,
            "initiative": 0.28,
            "care": 0.36,
            "emotional_pressure": 0.06,
        },
        "analysis": {
            "closeness": 0.34,
            "sexual_tension": 0.04,
            "explicitness": 0.00,
            "dominance": 0.20,
            "initiative": 0.34,
            "care": 0.46,
            "emotional_pressure": 0.10,
        },
        "tension": {
            "closeness": 0.48,
            "sexual_tension": 0.28,
            "explicitness": 0.08,
            "dominance": 0.26,
            "initiative": 0.42,
            "care": 0.48,
            "emotional_pressure": 0.18,
        },
        "personal_focus": {
            "closeness": 0.62,
            "sexual_tension": 0.38,
            "explicitness": 0.14,
            "dominance": 0.30,
            "initiative": 0.50,
            "care": 0.54,
            "emotional_pressure": 0.20,
        },
        "rare_layer": {
            "closeness": 0.76,
            "sexual_tension": 0.48,
            "explicitness": 0.18,
            "dominance": 0.34,
            "initiative": 0.56,
            "care": 0.58,
            "emotional_pressure": 0.22,
        },
    }
    MODE_BUDGET_ADJUSTMENTS = {
        "base": {"dominance": 0.00, "initiative": 0.00, "care": 0.00, "emotional_pressure": 0.00},
        "comfort": {"dominance": -0.12, "initiative": -0.08, "care": 0.30, "emotional_pressure": -0.10},
        "mentor": {"dominance": 0.10, "initiative": 0.12, "care": 0.04, "emotional_pressure": 0.02},
        "passion": {"closeness": 0.08, "sexual_tension": 0.12, "explicitness": 0.04, "care": 0.04},
        "night": {"dominance": 0.24, "initiative": 0.18, "sexual_tension": 0.10, "emotional_pressure": 0.08},
        "free_talk": {"play": 0.00},
        "dominant": {"dominance": 0.38, "initiative": 0.30, "sexual_tension": 0.06, "emotional_pressure": 0.12},
        "ptsd": {"dominance": -0.16, "initiative": -0.10, "care": 0.20, "emotional_pressure": -0.12},
    }

    def __init__(self, settings_service=None):
        self.settings_service = settings_service

    def update_access_level(self, state: dict) -> str:
        config = self._get_config()
        forced_level = str(config.get("forced_level") or "").strip()
        if forced_level in self.VALID_ACCESS_LEVELS:
            return forced_level

        interest = float(state.get("interest", 0.0) or 0.0)
        control = float(state.get("control", 1.0) or 1.0)
        attraction = float(state.get("attraction", 0.0) or 0.0)

        if interest < config["interest_observation_threshold"]:
            return "observation"
        if (
            attraction >= config["personal_focus_attraction_threshold"]
            and interest >= config["personal_focus_interest_threshold"]
            and control <= config["tension_control_threshold"]
        ):
            return "personal_focus"
        if (
            attraction >= config["tension_attraction_threshold"]
            and control <= config["tension_control_threshold"]
        ):
            return "tension"
        if (
            interest >= config["analysis_interest_threshold"]
            and control > config["analysis_control_threshold"]
        ):
            return "analysis"
        return str(config.get("default_level") or "analysis")

    def apply_safety_guardrails(
        self,
        *,
        state: dict,
        access_level: str,
        active_mode: str,
        user_message: str,
        is_proactive: bool = False,
    ) -> str:
        decision = self.evaluate_access(
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            user_message=user_message,
            is_proactive=is_proactive,
        )
        return str(decision["level"])

    def evaluate_access(
        self,
        *,
        state: dict,
        access_level: str,
        active_mode: str,
        user_message: str,
        is_proactive: bool = False,
    ) -> dict[str, object]:
        normalized_level = self._normalize_access_level(access_level)
        base_level = "observation" if normalized_level == "observation" else "analysis"
        normalized_mode = str(active_mode or "base").strip().lower() or "base"
        emotional_tone = str((state or {}).get("emotional_tone") or "").strip().lower()
        has_explicit_signal = self._has_explicit_intimacy_signal(user_message)

        final_level = normalized_level
        clamped = False
        reason = ""

        if normalized_mode not in self.INTIMATE_MODE_LEVELS:
            final_level = base_level
            if normalized_level != final_level or has_explicit_signal:
                clamped = True
                reason = "mode_not_intimate"
        elif is_proactive:
            final_level = base_level
            clamped = normalized_level != final_level or has_explicit_signal
            reason = "proactive_intimacy_block" if clamped else ""
        elif emotional_tone in self.HEAVY_EMOTIONAL_TONES:
            final_level = base_level
            clamped = normalized_level != final_level or has_explicit_signal
            reason = "heavy_emotional_tone" if clamped else ""
        elif not has_explicit_signal:
            final_level = base_level
            clamped = normalized_level != final_level
            reason = "no_explicit_signal" if clamped else ""
        else:
            allowed_level = self.INTIMATE_MODE_LEVELS[normalized_mode]
            if self._level_rank(final_level) > self._level_rank(allowed_level):
                final_level = allowed_level
                clamped = True
                reason = "mode_cap"

        budget = self._build_budget(
            level=final_level,
            active_mode=normalized_mode,
            emotional_tone=emotional_tone,
            has_explicit_signal=has_explicit_signal,
            is_proactive=is_proactive,
            clamp_reason=reason,
        )

        return {
            "level": final_level,
            "clamped": clamped,
            "reason": reason,
            "budget": budget,
        }

    def _build_budget(
        self,
        *,
        level: str,
        active_mode: str,
        emotional_tone: str,
        has_explicit_signal: bool,
        is_proactive: bool,
        clamp_reason: str,
    ) -> dict[str, float | str]:
        budget = dict(self.LEVEL_BUDGETS.get(level, self.LEVEL_BUDGETS["analysis"]))
        adjustments = self.MODE_BUDGET_ADJUSTMENTS.get(active_mode, {})

        for key, delta in adjustments.items():
            if key not in budget:
                continue
            budget[key] = self._clamp01(float(budget[key]) + float(delta))

        if active_mode in self.INTIMATE_MODE_LEVELS and not has_explicit_signal:
            budget["sexual_tension"] = min(float(budget["sexual_tension"]), 0.12)
            budget["explicitness"] = 0.00

        if is_proactive:
            budget["closeness"] = min(float(budget["closeness"]), 0.32)
            budget["sexual_tension"] = 0.00
            budget["explicitness"] = 0.00
            budget["emotional_pressure"] = min(float(budget["emotional_pressure"]), 0.10)

        if emotional_tone in self.HEAVY_EMOTIONAL_TONES:
            budget["sexual_tension"] = min(float(budget["sexual_tension"]), 0.05)
            budget["explicitness"] = 0.00
            budget["emotional_pressure"] = min(float(budget["emotional_pressure"]), 0.08)
            budget["care"] = max(float(budget["care"]), 0.60)
            budget["dominance"] = min(float(budget["dominance"]), 0.26)

        budget["clamp_reason"] = clamp_reason
        return budget

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

    def _has_explicit_intimacy_signal(self, user_message: str) -> bool:
        lowered = " ".join(str(user_message or "").lower().split())
        if not lowered:
            return False

        if any(marker in lowered for marker in self.NEGATIVE_INTIMACY_MARKERS):
            return False

        return any(marker in lowered for marker in self.EXPLICIT_INTIMACY_MARKERS)

    def _normalize_access_level(self, access_level: str) -> str:
        normalized = str(access_level or "analysis").strip().lower() or "analysis"
        if normalized in self.VALID_ACCESS_LEVELS:
            return normalized
        return "analysis"

    @classmethod
    def _level_rank(cls, level: str) -> int:
        order = ["observation", "analysis", "tension", "personal_focus", "rare_layer"]
        try:
            return order.index(level)
        except ValueError:
            return order.index("analysis")

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))
