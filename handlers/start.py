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


def _extract_referrer_id(text: str, prefix: str) -> int | None:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    parameter = parts[1].strip()
    if not parameter.startswith(prefix):
        return None
    raw_id = parameter[len(prefix):].strip()
    return int(raw_id) if raw_id.isdigit() else None


@router.message(CommandStart())
async def start_handler(
    message: Message,
    user_service,
    admin_settings_service,
    referral_service,
):
    is_new_user = await user_service.ensure_user(message.from_user)
    runtime = admin_settings_service.get_runtime_settings()
    ui_settings = runtime["ui"]
    referral_settings = runtime["referral"]
    keyboard = get_main_keyboard(ui_settings)

    referrer_user_id = _extract_referrer_id(
        message.text or "",
        referral_settings["start_parameter_prefix"],
    )
    if referrer_user_id and is_new_user:
        created = await referral_service.register_referral(
            referrer_user_id=referrer_user_id,
            referred_user_id=message.from_user.id,
        )
        if created and referral_settings["referred_welcome_message"]:
            await message.answer(referral_settings["referred_welcome_message"], reply_markup=keyboard)

    if await user_service.is_admin(message.from_user.id):
        await message.answer(ui_settings["welcome_admin_text"], reply_markup=keyboard)
        return

    if referrer_user_id and is_new_user:
        await message.answer(ui_settings["welcome_user_text"], reply_markup=keyboard)
        return

    await message.answer(ui_settings["welcome_user_text"], reply_markup=keyboard)
