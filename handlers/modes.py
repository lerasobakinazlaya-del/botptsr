from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from handlers.payments import (
    CALLBACK_PREMIUM_BACK_TO_MODES,
    OFFER_TRIGGER_MODE_LOCKED,
    show_premium_menu,
)
from keyboards.modes_keyboard import get_modes_keyboard


router = Router(name="modes-router")

CALLBACK_OPEN_MODES = "open_modes"
CALLBACK_MODE_PREFIX = "mode:"


def build_modes_menu_text(user: dict, runtime_settings: dict, mode_catalog: dict) -> str:
    ui_settings = runtime_settings.get("ui", {})
    title = str(ui_settings.get("modes_title") or "Выбери режим общения:").strip()
    text = title or "Выбери режим общения:"
    if not bool((user or {}).get("is_premium")):
        premium_modes = [
            str(mode.get("name") or key)
            for key, mode in (mode_catalog or {}).items()
            if bool(mode.get("is_premium"))
        ]
        premium_button = str(ui_settings.get("premium_button_text") or "Полный доступ").strip()
        if premium_modes:
            preview = ", ".join(premium_modes[:2])
            text = f"{text}\n\n{premium_button}: откроет режимы {preview} и более глубокие ответы без короткого обрыва."
    return text


async def show_modes_menu(message: Message, user_service, admin_settings_service):
    runtime_settings = admin_settings_service.get_runtime_settings()
    ui_settings = runtime_settings["ui"]
    mode_catalog = admin_settings_service.get_mode_catalog()
    user = await user_service.get_user(message.from_user.id)
    if not user:
        await message.answer(ui_settings["user_not_found_text"])
        return False

    await message.answer(
        text=build_modes_menu_text(user, runtime_settings, mode_catalog),
        reply_markup=get_modes_keyboard(user, runtime_settings, mode_catalog),
    )
    return True


@router.callback_query(F.data == CALLBACK_OPEN_MODES)
async def open_modes_handler(callback: CallbackQuery, user_service, admin_settings_service):
    runtime_settings = admin_settings_service.get_runtime_settings()
    ui_settings = runtime_settings["ui"]
    mode_catalog = admin_settings_service.get_mode_catalog()
    user = await user_service.get_user(callback.from_user.id)
    if not user:
        await callback.answer(ui_settings["user_not_found_text"], show_alert=True)
        return

    try:
        await callback.message.edit_text(
            text=build_modes_menu_text(user, runtime_settings, mode_catalog),
            reply_markup=get_modes_keyboard(user, runtime_settings, mode_catalog),
        )
    except TelegramBadRequest:
        pass

    await callback.answer()


@router.callback_query(F.data == CALLBACK_PREMIUM_BACK_TO_MODES)
async def premium_back_to_modes_handler(callback: CallbackQuery, user_service, admin_settings_service):
    await open_modes_handler(callback, user_service, admin_settings_service)


@router.callback_query(F.data.startswith(CALLBACK_MODE_PREFIX))
async def change_mode_handler(
    callback: CallbackQuery,
    user_service,
    state_repository,
    admin_settings_service,
    mode_access_service,
    payment_service,
):
    runtime_settings = admin_settings_service.get_runtime_settings()
    ui_settings = runtime_settings["ui"]
    mode_catalog = admin_settings_service.get_mode_catalog()
    mode_key = callback.data.replace(CALLBACK_MODE_PREFIX, "")

    if mode_key not in mode_catalog:
        await callback.answer(ui_settings["unknown_mode_text"], show_alert=True)
        return

    user = await user_service.get_user(callback.from_user.id)
    if not user:
        await callback.answer(ui_settings["user_not_found_text"], show_alert=True)
        return

    state = await state_repository.get(callback.from_user.id)
    can_select_mode = mode_access_service.can_select_mode(
        user=user,
        mode_key=mode_key,
        state=state,
        runtime_settings=runtime_settings,
        mode_catalog=mode_catalog,
    )

    mode_meta = mode_catalog.get(mode_key, {})
    mode_name = str(mode_meta.get("name") or mode_key)
    activation_phrase = str(mode_meta.get("activation_phrase") or "").strip()

    if bool(mode_meta.get("is_premium")) and not user.get("is_premium") and not can_select_mode:
        await callback.answer(ui_settings["mode_locked_text"], show_alert=True)
        if callback.message is not None:
            await show_premium_menu(
                callback.message,
                payment_service,
                user_service,
                admin_settings_service,
                trigger=OFFER_TRIGGER_MODE_LOCKED,
                mode_name=mode_name,
                premium_limit=int(runtime_settings["limits"].get("premium_daily_messages_limit", 200)),
                edit_current=True,
            )
        return

    await user_service.set_mode(callback.from_user.id, mode_key)
    await state_repository.set_active_mode(callback.from_user.id, mode_key)
    user["active_mode"] = mode_key
    text = ui_settings["mode_saved_template"].format(
        mode_name=mode_name,
        activation_phrase=activation_phrase,
    )

    try:
        await callback.message.edit_text(
            text=text,
            reply_markup=get_modes_keyboard(user, runtime_settings, mode_catalog),
        )
    except TelegramBadRequest:
        pass

    await callback.answer(ui_settings["mode_saved_toast"])
