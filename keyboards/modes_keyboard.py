from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.modes import get_ordered_modes
from handlers.payments import CALLBACK_BUY_PREMIUM
from services.payment_formatting import format_access_days_label, format_price_label


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


def _build_premium_button_text(runtime_settings: dict) -> str:
    ui_settings = runtime_settings.get("ui", {}) if isinstance(runtime_settings, dict) else {}
    payment_settings = runtime_settings.get("payment", {}) if isinstance(runtime_settings, dict) else {}
    fallback = str(ui_settings.get("premium_button_text") or "Premium").strip() or "Premium"
    template = str(ui_settings.get("premium_button_text_template") or "").strip()
    if not template:
        return fallback

    access_days = max(1, int(payment_settings.get("access_duration_days", 30)))
    try:
        return template.format(
            price_label=format_price_label(payment_settings),
            access_days=access_days,
            access_days_label=format_access_days_label(access_days),
        ).strip() or fallback
    except (KeyError, ValueError):
        return fallback


def get_modes_keyboard(
    user,
    runtime_settings: dict | None = None,
    mode_catalog: dict | None = None,
) -> InlineKeyboardMarkup:
    settings = runtime_settings or {}
    ui_settings = settings.get("ui", {}) if isinstance(settings, dict) else {}
    premium_marker = str(ui_settings.get("modes_premium_marker") or "🔒").strip() or "🔒"
    buttons = []

    for mode in _ordered_modes(mode_catalog):
        button_title = f"{mode['icon']} {mode['name']}"
        if mode["is_premium"] and not user.get("is_premium"):
            button_title = f"{button_title} {premium_marker}".strip()

        buttons.append(
            [
                InlineKeyboardButton(
                    text=button_title,
                    callback_data=f"mode:{mode['key']}",
                )
            ]
        )

    if not user.get("is_premium"):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=_build_premium_button_text(settings),
                    callback_data=CALLBACK_BUY_PREMIUM,
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)
