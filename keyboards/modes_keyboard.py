from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.modes import get_ordered_modes
from handlers.payments import CALLBACK_BUY_PREMIUM


def _ordered_modes(mode_catalog: dict | None = None) -> list[dict]:
    if isinstance(mode_catalog, dict) and mode_catalog:
        return sorted(
            [
                {
                    "key": str(key),
                    "name": str(value.get("name") or key),
                    "icon": str(value.get("icon") or "•"),
                    "is_premium": bool(value.get("is_premium")),
                    "sort_order": int(value.get("sort_order", 0)),
                }
                for key, value in mode_catalog.items()
            ],
            key=lambda item: (item["sort_order"], item["name"].lower()),
        )

    return [
        {
            "key": mode.key,
            "name": mode.name,
            "icon": mode.icon,
            "is_premium": mode.is_premium,
            "sort_order": mode.sort_order,
        }
        for mode in get_ordered_modes()
    ]


def _premium_mode_suffix(mode_key: str, user: dict, limits: dict) -> str:
    if user.get("is_premium"):
        return ""

    mode_daily_limits = limits.get("mode_daily_limits", {}) if isinstance(limits, dict) else {}
    preview_enabled = bool(limits.get("mode_preview_enabled"))
    preview_limit = int(mode_daily_limits.get(mode_key, 0) or 0)
    if preview_enabled and preview_limit > 0:
        return f" • Премиум ({preview_limit}/день)"
    return " • Премиум"


def get_modes_keyboard(
    user,
    runtime_settings: dict | None = None,
    mode_catalog: dict | None = None,
) -> InlineKeyboardMarkup:
    limits = (runtime_settings or {}).get("limits", {})
    ui_settings = (runtime_settings or {}).get("ui", {})
    buttons = []

    for mode in _ordered_modes(mode_catalog):
        button_title = f"{mode['icon']} {mode['name']}"
        if mode["is_premium"]:
            button_title += _premium_mode_suffix(mode["key"], user, limits)

        buttons.append(
            [
                InlineKeyboardButton(
                    text=button_title,
                    callback_data=f"mode:{mode['key']}",
                )
            ]
        )

    if not user.get("is_premium"):
        premium_button_text = str(ui_settings.get("premium_button_text") or "Premium").strip() or "Premium"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=premium_button_text,
                    callback_data=CALLBACK_BUY_PREMIUM,
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)
