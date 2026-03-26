from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from config.modes import get_mode, get_modes, get_premium_modes
from keyboards.modes_keyboard import get_modes_keyboard


router = Router(name="modes-router")

CALLBACK_OPEN_MODES = "open_modes"
CALLBACK_MODE_PREFIX = "mode:"

async def show_modes_menu(message: Message, user_service, admin_settings_service):
    ui_settings = admin_settings_service.get_runtime_settings()["ui"]
    user = await user_service.get_user(message.from_user.id)
    if not user:
        await message.answer(ui_settings["user_not_found_text"])
        return False

    await message.answer(
        text=ui_settings["modes_title"],
        reply_markup=get_modes_keyboard(user),
    )
    return True


@router.callback_query(F.data == CALLBACK_OPEN_MODES)
async def open_modes_handler(callback: CallbackQuery, user_service, admin_settings_service):
    ui_settings = admin_settings_service.get_runtime_settings()["ui"]
    user = await user_service.get_user(callback.from_user.id)
    if not user:
        await callback.answer(ui_settings["user_not_found_text"], show_alert=True)
        return

    try:
        await callback.message.edit_text(
            text=ui_settings["modes_title"],
            reply_markup=get_modes_keyboard(user),
        )
    except TelegramBadRequest:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith(CALLBACK_MODE_PREFIX))
async def change_mode_handler(
    callback: CallbackQuery,
    user_service,
    state_repository,
    admin_settings_service,
):
    ui_settings = admin_settings_service.get_runtime_settings()["ui"]
    mode_key = callback.data.replace(CALLBACK_MODE_PREFIX, "")
    modes = get_modes()

    if mode_key not in modes:
        await callback.answer(ui_settings["unknown_mode_text"], show_alert=True)
        return

    user = await user_service.get_user(callback.from_user.id)
    if not user:
        await callback.answer(ui_settings["user_not_found_text"], show_alert=True)
        return

    if mode_key in get_premium_modes() and not user.get("is_premium"):
        await callback.answer(ui_settings["mode_locked_text"], show_alert=True)
        return

    await user_service.set_mode(callback.from_user.id, mode_key)
    await state_repository.set_active_mode(callback.from_user.id, mode_key)
    user["active_mode"] = mode_key
    mode = get_mode(mode_key)
    text = ui_settings["mode_saved_template"].format(
        mode_name=mode.name,
        activation_phrase=mode.activation_phrase,
    )

    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_modes_keyboard(user),
        )
    except TelegramBadRequest:
        pass

    await callback.answer(ui_settings["mode_saved_toast"])
