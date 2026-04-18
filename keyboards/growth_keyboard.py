from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_referral_keyboard(*, share_url: str, share_button_text: str, info_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=share_button_text, url=share_url)],
            [InlineKeyboardButton(text="Как работают бонусы", callback_data=info_callback)],
        ]
    )


def build_growth_reply_keyboard(*, share_callback: str, referral_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Поделиться инсайтом", callback_data=share_callback),
                InlineKeyboardButton(text="Пригласить друга", callback_data=referral_callback),
            ]
        ]
    )


def build_telegram_share_url(text: str) -> str:
    return f"https://t.me/share/url?text={quote(text)}"
