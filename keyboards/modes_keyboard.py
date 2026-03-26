from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.modes import get_ordered_modes, get_premium_modes


def get_modes_keyboard(user, runtime_settings: dict | None = None) -> InlineKeyboardMarkup:
    premium_modes = get_premium_modes()
    limits = (runtime_settings or {}).get("limits", {})
    preview_enabled = bool(limits.get("mode_preview_enabled"))
    mode_daily_limits = limits.get("mode_daily_limits", {}) if isinstance(limits, dict) else {}
    buttons = []

    for mode in get_ordered_modes():
        button_title = f"{mode.icon} {mode.name}"
        if mode.key in premium_modes and not user["is_premium"]:
            preview_limit = int(mode_daily_limits.get(mode.key, 0) or 0)
            button_title += " 🧪" if preview_enabled and preview_limit > 0 else " 🔒"

        buttons.append(
            [
                InlineKeyboardButton(
                    text=button_title,
                    callback_data=f"mode:{mode.key}",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)
