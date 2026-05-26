from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.ai_profile_service import resolve_ai_profile


class ProductEntitlementsService:
    """Single product contract for plan, mode, model, and quota decisions."""

    PLAN_ORDER = {"free": 0, "pro": 1, "premium": 2}
    VALID_PLANS = frozenset(PLAN_ORDER)
    MODE_USAGE_STATE_KEY = "mode_daily_usage"
    MAX_TRACKED_DAYS = 14

    def normalize_plan(self, user: dict[str, Any] | None) -> str:
        normalized = str((user or {}).get("subscription_plan") or "").strip().lower()
        if normalized in self.VALID_PLANS:
            return normalized
        return "premium" if bool((user or {}).get("is_premium")) else "free"

    def is_paid(self, user: dict[str, Any] | None) -> bool:
        return self.normalize_plan(user) in {"pro", "premium"}

    def get_plan_daily_limit(
        self,
        *,
        user: dict[str, Any] | None = None,
        plan_key: str | None = None,
        limits_settings: dict[str, Any],
    ) -> dict[str, Any]:
        plan = self._normalize_plan_key(plan_key or self.normalize_plan(user))
        prefix = "premium" if plan == "premium" else "pro" if plan == "pro" else "free"
        default_limit = 200 if plan == "premium" else 80 if plan == "pro" else 12
        return {
            "plan": plan,
            "enabled": bool(limits_settings.get(f"{prefix}_daily_messages_enabled", True)),
            "limit": max(1, int(limits_settings.get(f"{prefix}_daily_messages_limit", default_limit))),
            "limit_message": str(limits_settings.get(f"{prefix}_daily_limit_message") or "").strip(),
            "warning_template": str(limits_settings.get(f"{prefix}_daily_warning_template") or "").strip(),
            "warning_thresholds": self._normalize_int_list(
                limits_settings.get(f"{prefix}_daily_warning_thresholds")
            ),
        }

    def get_monthly_usage_policy(
        self,
        *,
        user: dict[str, Any] | None = None,
        plan_key: str | None = None,
        limits_settings: dict[str, Any],
    ) -> dict[str, Any]:
        plan = self._normalize_plan_key(plan_key or self.normalize_plan(user))
        prefix = "premium" if plan == "premium" else "pro" if plan == "pro" else "free"
        messages_enabled = bool(limits_settings.get(f"{prefix}_monthly_messages_enabled", plan == "free"))
        tokens_enabled = bool(limits_settings.get(f"{prefix}_monthly_tokens_enabled", plan == "free"))
        return {
            "plan": plan,
            "messages_enabled": messages_enabled,
            "messages_limit": self._normalize_optional_limit(
                limits_settings.get(f"{prefix}_monthly_messages_limit"),
                default=40 if plan == "free" else 0,
                enabled=messages_enabled,
            ),
            "messages_limit_message": str(
                limits_settings.get(f"{prefix}_monthly_limit_message")
                or "Ты исчерпал бесплатный лимит сообщений на этот месяц. Чтобы продолжить без паузы, открой платный план."
            ).strip(),
            "tokens_enabled": tokens_enabled,
            "tokens_limit": self._normalize_optional_limit(
                limits_settings.get(f"{prefix}_monthly_tokens_limit"),
                default=12000 if plan == "free" else 0,
                enabled=tokens_enabled,
            ),
            "tokens_limit_message": str(
                limits_settings.get(f"{prefix}_monthly_tokens_limit_message")
                or "Ты исчерпал бесплатный лимит токенов на этот месяц. Чтобы продолжить, открой платный план."
            ).strip(),
        }

    def get_hard_usage_limit_status(
        self,
        *,
        user: dict[str, Any] | None,
        limits_settings: dict[str, Any],
        monthly_messages: int,
        monthly_chat_tokens: int,
    ) -> dict[str, Any]:
        policy = self.get_monthly_usage_policy(user=user, limits_settings=limits_settings)
        plan = str(policy["plan"])
        messages_used = max(0, int(monthly_messages or 0))
        tokens_used = max(0, int(monthly_chat_tokens or 0))

        if bool(policy["messages_enabled"]) and messages_used >= int(policy["messages_limit"]):
            return {
                "allowed": False,
                "reason": "monthly_messages",
                "plan": plan,
                "used": messages_used,
                "limit": int(policy["messages_limit"]),
                "message": str(policy["messages_limit_message"]).format(
                    used=messages_used,
                    limit=int(policy["messages_limit"]),
                ),
            }

        if bool(policy["tokens_enabled"]) and tokens_used >= int(policy["tokens_limit"]):
            return {
                "allowed": False,
                "reason": "monthly_chat_tokens",
                "plan": plan,
                "used": tokens_used,
                "limit": int(policy["tokens_limit"]),
                "message": str(policy["tokens_limit_message"]).format(
                    used=tokens_used,
                    limit=int(policy["tokens_limit"]),
                ),
            }

        return {
            "allowed": True,
            "reason": None,
            "plan": plan,
            "monthly_messages_remaining": (
                max(0, int(policy["messages_limit"]) - messages_used)
                if bool(policy["messages_enabled"])
                else None
            ),
            "monthly_chat_tokens_remaining": (
                max(0, int(policy["tokens_limit"]) - tokens_used)
                if bool(policy["tokens_enabled"])
                else None
            ),
        }

    def get_ai_profile(
        self,
        *,
        runtime_settings: dict[str, Any],
        active_mode: str,
        user: dict[str, Any] | None = None,
        plan_key: str | None = None,
    ) -> dict[str, Any]:
        return resolve_ai_profile(
            runtime_settings.get("ai", {}),
            active_mode,
            self._normalize_plan_key(plan_key or self.normalize_plan(user)),
        )

    def get_mode_access_status(
        self,
        *,
        user: dict[str, Any] | None,
        mode_key: str,
        state: dict[str, Any] | None,
        runtime_settings: dict[str, Any],
        mode_catalog: dict[str, Any],
    ) -> dict[str, Any]:
        min_plan = self._mode_min_plan(mode_catalog.get(mode_key, {}))
        plan = self.normalize_plan(user)
        if self.PLAN_ORDER[plan] >= self.PLAN_ORDER[min_plan]:
            return {
                "allowed": True,
                "is_preview": False,
                "daily_limit": None,
                "remaining": None,
                "plan": plan,
                "min_plan": min_plan,
            }

        limit = self._resolve_preview_limit(
            mode_key=mode_key,
            runtime_settings=runtime_settings,
        )
        remaining = max(0, limit - self._get_today_mode_usage(state or {}, mode_key))
        return {
            "allowed": remaining > 0,
            "is_preview": True,
            "daily_limit": limit,
            "remaining": remaining,
            "plan": plan,
            "min_plan": min_plan,
        }

    def register_successful_mode_message(
        self,
        state: dict[str, Any] | None,
        *,
        user: dict[str, Any] | None,
        mode_key: str,
        runtime_settings: dict[str, Any],
        mode_catalog: dict[str, Any],
    ) -> dict[str, Any]:
        current_state = dict(state or {})
        status = self.get_mode_access_status(
            user=user,
            mode_key=mode_key,
            state=current_state,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        if not bool(status.get("is_preview")):
            return current_state

        usage = self._normalized_usage_map(current_state.get(self.MODE_USAGE_STATE_KEY))
        today_key = self._today_key()
        usage.setdefault(today_key, {})
        usage[today_key][mode_key] = int(usage[today_key].get(mode_key, 0)) + 1
        current_state[self.MODE_USAGE_STATE_KEY] = self._prune_usage(usage)
        return current_state

    def build_snapshot(
        self,
        *,
        user: dict[str, Any] | None,
        runtime_settings: dict[str, Any],
        mode_catalog: dict[str, Any],
        active_mode: str = "base",
        state: dict[str, Any] | None = None,
        today_messages: int | None = None,
        monthly_messages: int | None = None,
        monthly_chat_tokens: int | None = None,
    ) -> dict[str, Any]:
        plan = self.normalize_plan(user)
        limits = runtime_settings.get("limits", {})
        daily = self.get_plan_daily_limit(
            user=user,
            limits_settings=limits,
        )
        mode_access = self.get_mode_access_status(
            user=user,
            mode_key=active_mode,
            state=state or {},
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        used_today = int(today_messages or 0)
        daily_remaining = max(0, int(daily["limit"]) - used_today)
        monthly_policy = self.get_monthly_usage_policy(user=user, limits_settings=limits)
        used_monthly_messages = int(monthly_messages or 0)
        used_monthly_tokens = int(monthly_chat_tokens or 0)
        return {
            "plan": plan,
            "is_paid": plan in {"pro", "premium"},
            "daily_messages": {
                **daily,
                "used": used_today,
                "remaining": daily_remaining,
            },
            "monthly_messages": {
                "used": used_monthly_messages,
                "remaining": (
                    max(0, int(monthly_policy["messages_limit"]) - used_monthly_messages)
                    if bool(monthly_policy["messages_enabled"])
                    else None
                ),
                "limit": int(monthly_policy["messages_limit"]) if bool(monthly_policy["messages_enabled"]) else None,
                "enabled": bool(monthly_policy["messages_enabled"]),
            },
            "monthly_chat_tokens": {
                "used": used_monthly_tokens,
                "remaining": (
                    max(0, int(monthly_policy["tokens_limit"]) - used_monthly_tokens)
                    if bool(monthly_policy["tokens_enabled"])
                    else None
                ),
                "limit": int(monthly_policy["tokens_limit"]) if bool(monthly_policy["tokens_enabled"]) else None,
                "enabled": bool(monthly_policy["tokens_enabled"]),
            },
            "active_mode": active_mode,
            "mode_access": mode_access,
            "ai_profile": self.get_ai_profile(
                runtime_settings=runtime_settings,
                active_mode=active_mode,
                plan_key=plan,
            ),
        }

    def _mode_min_plan(self, mode_meta: dict[str, Any]) -> str:
        explicit = self._normalize_plan_key(mode_meta.get("min_plan"), fallback="")
        if explicit:
            return explicit
        return "pro" if bool(mode_meta.get("is_premium")) else "free"

    def _resolve_preview_limit(
        self,
        *,
        mode_key: str,
        runtime_settings: dict[str, Any],
    ) -> int:
        limits = runtime_settings.get("limits", {})
        if not bool(limits.get("mode_preview_enabled")):
            return 0
        configured = limits.get("mode_daily_limits", {})
        default_limit = max(0, int(limits.get("mode_preview_default_limit", 0) or 0))
        try:
            return max(0, int((configured or {}).get(mode_key, default_limit)))
        except (TypeError, ValueError):
            return default_limit

    def _get_today_mode_usage(self, state: dict[str, Any], mode_key: str) -> int:
        usage = self._normalized_usage_map((state or {}).get(self.MODE_USAGE_STATE_KEY))
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

    def _normalize_plan_key(self, value: Any, *, fallback: str = "free") -> str:
        normalized = str(value or "").strip().lower()
        if normalized in self.VALID_PLANS:
            return normalized
        return fallback

    def _normalize_optional_limit(self, value: Any, *, default: int, enabled: bool) -> int:
        if not enabled:
            return 0
        try:
            return max(1, int(value if value is not None else default))
        except (TypeError, ValueError):
            return max(1, int(default))

    def _normalize_int_list(self, raw: object) -> list[int]:
        if isinstance(raw, str):
            items = raw.replace(",", "\n").splitlines()
        else:
            items = list(raw or [])

        normalized: list[int] = []
        for item in items:
            try:
                normalized.append(int(item))
            except (TypeError, ValueError):
                continue
        return normalized
