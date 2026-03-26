from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.modes import get_ordered_modes, get_premium_modes


def get_modes_keyboard(user) -> InlineKeyboardMarkup:
    premium_modes = get_premium_modes()
    buttons = []

    for mode in get_ordered_modes():
        button_title = f"{mode.icon} {mode.name}"
        if mode.key in premium_modes and not user["is_premium"]:
            button_title += " 🔒"

        buttons.append(
            [
                InlineKeyboardButton(
                    text=button_title,
                    callback_data=f"mode:{mode.key}",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)
