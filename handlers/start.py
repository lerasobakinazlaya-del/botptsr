from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup


router = Router()

WRITE_BUTTON_TEXT = "💬 Написать"
MODES_BUTTON_TEXT = "🎛 Режимы"
PREMIUM_BUTTON_TEXT = "💎 Premium"


def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=WRITE_BUTTON_TEXT)],
            [KeyboardButton(text=MODES_BUTTON_TEXT)],
            [KeyboardButton(text=PREMIUM_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напиши мне...",
    )


@router.message(CommandStart())
async def start_handler(message: Message, user_service, settings):
    await user_service.register_user(message.from_user)

    keyboard = get_main_keyboard()

    if message.from_user.id in settings.admin_id:
        await message.answer(
            "🔐 Панель администратора активирована.\n\n"
            "Бот работает в штатном режиме.",
            reply_markup=keyboard,
        )
        return

    await message.answer(
        "Привет.\n\n"
        "Я рядом.\n"
        "Можешь просто написать мне.\n\n"
        "Или выбрать режим общения 🎛\n"
        "Или оформить Premium 💎",
        reply_markup=keyboard,
    )
