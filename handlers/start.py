from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup


router = Router()


def get_main_keyboard(ui_settings: dict) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ui_settings["write_button_text"])],
            [KeyboardButton(text=ui_settings["modes_button_text"])],
            [KeyboardButton(text=ui_settings["premium_button_text"])],
        ],
        resize_keyboard=True,
        input_field_placeholder=ui_settings["input_placeholder"],
    )


@router.message(CommandStart())
async def start_handler(message: Message, user_service, settings, admin_settings_service):
    await user_service.register_user(message.from_user)
    ui_settings = admin_settings_service.get_runtime_settings()["ui"]
    keyboard = get_main_keyboard(ui_settings)

    if message.from_user.id in settings.admin_id:
        await message.answer(
            ui_settings["welcome_admin_text"],
            reply_markup=keyboard,
        )
        return

    await message.answer(
        ui_settings["welcome_user_text"],
        reply_markup=keyboard,
    )
