from typing import Any

from services.product_entitlements_service import ProductEntitlementsService


class ModeAccessService:
    USAGE_STATE_KEY = ProductEntitlementsService.MODE_USAGE_STATE_KEY
    MAX_TRACKED_DAYS = ProductEntitlementsService.MAX_TRACKED_DAYS

    def __init__(self, entitlements_service: ProductEntitlementsService | None = None):
        self.entitlements_service = entitlements_service or ProductEntitlementsService()

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
        status = self.entitlements_service.get_mode_access_status(
            user=user,
            mode_key=mode_key,
            state=state,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        return {
            "allowed": status["allowed"],
            "is_preview": status["is_preview"],
            "daily_limit": status["daily_limit"],
            "remaining": status["remaining"],
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
        return self.entitlements_service.register_successful_mode_message(
            state,
            user=user,
            mode_key=mode_key,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
