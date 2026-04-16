from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, KeyboardButton, Message, ReplyKeyboardMarkup


router = Router()
PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _build_welcome_followup_text(ui_settings: dict) -> str:
    return str(ui_settings.get("welcome_followup_text") or "").strip()


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
    avatar_path = str(ui_settings.get("start_avatar_path") or "").strip()
    avatar_file = PROJECT_ROOT / avatar_path if avatar_path else None

    async def send_welcome(text: str) -> None:
        if avatar_file and avatar_file.exists():
            await message.answer_photo(
                photo=FSInputFile(avatar_file),
                caption=text,
                reply_markup=keyboard,
            )
            return
        await message.answer(text, reply_markup=keyboard)

    async def send_user_welcome() -> None:
        await send_welcome(ui_settings["welcome_user_text"])
        if not is_new_user:
            return
        followup_text = _build_welcome_followup_text(ui_settings)
        if followup_text:
            await message.answer(followup_text)

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
        await send_welcome(ui_settings["welcome_admin_text"])
        return

    if referrer_user_id and is_new_user:
        await send_user_welcome()
        return

    await send_user_welcome()
