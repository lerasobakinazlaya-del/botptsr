from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.modes import MODES, PREMIUM_MODES


MODE_BUTTONS = [
    ("💬 Базовый", "base"),
    ("🫂 Поддержка", "comfort"),
    ("🔥 Близость", "passion"),
    ("🧠 Наставник", "mentor"),
    ("🌙 Ночной", "night"),
    ("👑 Доминирующий", "dominant"),
]


def get_modes_keyboard(user) -> InlineKeyboardMarkup:
    buttons = []

    for title, mode_key in MODE_BUTTONS:
        button_title = title
        if mode_key in PREMIUM_MODES and not user["is_premium"]:
            button_title += " 🔒"

        mode = MODES[mode_key]
        buttons.append(
            [
                InlineKeyboardButton(
                    text=button_title,
                    callback_data=f"mode:{mode.key}",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)
