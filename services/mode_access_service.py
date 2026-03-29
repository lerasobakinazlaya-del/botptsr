from datetime import datetime, timezone
from typing import Any


class ModeAccessService:
    USAGE_STATE_KEY = "mode_daily_usage"
    MAX_TRACKED_DAYS = 14

    def can_select_mode(
        self,
        *,
        user: dict[str, Any],
        mode_key: str,
        state: dict[str, Any],
        runtime_settings: dict[str, Any],
        mode_catalog: dict[str, Any],
    ) -> bool:
        return self.get_selection_status(
            user=user,
            mode_key=mode_key,
            state=state,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )["allowed"]

    def get_selection_status(
        self,
        *,
        user: dict[str, Any],
        mode_key: str,
        state: dict[str, Any],
        runtime_settings: dict[str, Any],
        mode_catalog: dict[str, Any],
    ) -> dict[str, Any]:
        limit = self._resolve_daily_limit(
            user=user,
            mode_key=mode_key,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        if limit is None:
            return {"allowed": True, "is_preview": False, "daily_limit": None, "remaining": None}

        remaining = max(0, limit - self._get_today_usage(state, mode_key))
        return {
            "allowed": remaining > 0,
            "is_preview": True,
            "daily_limit": limit,
            "remaining": remaining,
        }

    def register_successful_message(
        self,
        state: dict[str, Any] | None,
        *,
        mode_key: str,
        user: dict[str, Any],
        runtime_settings: dict[str, Any],
        mode_catalog: dict[str, Any],
    ) -> dict[str, Any]:
        current_state = (state or {}).copy()
        limit = self._resolve_daily_limit(
            user=user,
            mode_key=mode_key,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        if limit is None:
            return current_state

        usage = self._normalized_usage_map(current_state.get(self.USAGE_STATE_KEY))
        today_key = self._today_key()
        usage.setdefault(today_key, {})
        usage[today_key][mode_key] = int(usage[today_key].get(mode_key, 0)) + 1
        current_state[self.USAGE_STATE_KEY] = self._prune_usage(usage)
        return current_state

    def _resolve_daily_limit(
        self,
        *,
        user: dict[str, Any],
        mode_key: str,
        runtime_settings: dict[str, Any],
        mode_catalog: dict[str, Any],
    ) -> int | None:
        if user.get("is_premium"):
            return None

        mode_meta = mode_catalog.get(mode_key, {})
        if not mode_meta.get("is_premium"):
            return None

        limits = runtime_settings.get("limits", {})
        if not bool(limits.get("mode_preview_enabled")):
            return 0

        configured = limits.get("mode_daily_limits", {})
        default_limit = max(0, int(limits.get("mode_preview_default_limit", 0) or 0))
        try:
            return max(0, int(configured.get(mode_key, default_limit)))
        except (TypeError, ValueError):
            return default_limit

    def _get_today_usage(self, state: dict[str, Any], mode_key: str) -> int:
        usage = self._normalized_usage_map((state or {}).get(self.USAGE_STATE_KEY))
        return int(usage.get(self._today_key(), {}).get(mode_key, 0))

    def _normalized_usage_map(self, raw: Any) -> dict[str, dict[str, int]]:
        if not isinstance(raw, dict):
            return {}

        normalized: dict[str, dict[str, int]] = {}
        for day, day_values in raw.items():
            if not isinstance(day_values, dict):
                continue
            normalized[str(day)] = {}
            for mode_key, count in day_values.items():
                try:
                    normalized[str(day)][str(mode_key)] = max(0, int(count))
                except (TypeError, ValueError):
                    continue
        return normalized

    def _prune_usage(self, usage: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        ordered_days = sorted(usage.keys(), reverse=True)
        return {day: usage[day] for day in ordered_days[: self.MAX_TRACKED_DAYS]}

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()
