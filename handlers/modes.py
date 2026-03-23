from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from config.modes import MODES, PREMIUM_MODES
from keyboards.modes_keyboard import get_modes_keyboard


router = Router(name="modes-router")

MODES_BUTTON_TEXT = "🎛 Режимы"
CALLBACK_OPEN_MODES = "open_modes"
CALLBACK_MODE_PREFIX = "mode:"


@router.message(F.text == MODES_BUTTON_TEXT)
async def open_modes_from_text(message: Message, user_service):
    user = await user_service.get_user(message.from_user.id)
    if not user:
        await message.answer("Пользователь не найден.")
        return

    await message.answer(
        text="Выбери режим общения:",
        reply_markup=get_modes_keyboard(user),
    )


@router.callback_query(F.data == CALLBACK_OPEN_MODES)
async def open_modes_handler(callback: CallbackQuery, user_service):
    user = await user_service.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            text="Выбери режим общения:",
            reply_markup=get_modes_keyboard(user),
        )
    except TelegramBadRequest:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith(CALLBACK_MODE_PREFIX))
async def change_mode_handler(callback: CallbackQuery, user_service, state_repository):
    mode_key = callback.data.replace(CALLBACK_MODE_PREFIX, "")

    if mode_key not in MODES:
        await callback.answer("Неизвестный режим.", show_alert=True)
        return

    user = await user_service.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    if mode_key in PREMIUM_MODES and not user.get("is_premium"):
        await callback.answer(
            "Этот режим доступен только в Premium 🔒",
            show_alert=True,
        )
        return

    await user_service.set_mode(callback.from_user.id, mode_key)
    await state_repository.set_active_mode(callback.from_user.id, mode_key)
    user["active_mode"] = mode_key

    mode = MODES[mode_key]

    try:
        await callback.message.edit_text(
            text=(
                f"Режим активирован: {mode.name}\n\n"
                f"{mode.activation_phrase}"
            ),
            reply_markup=get_modes_keyboard(user),
        )
    except TelegramBadRequest:
        pass

    await callback.answer("Готово ✅")
