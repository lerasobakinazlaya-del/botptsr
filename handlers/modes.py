from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from handlers.payments import OFFER_TRIGGER_MODE_LOCKED, send_premium_offer
from keyboards.modes_keyboard import get_modes_keyboard
from services.payment_formatting import format_access_days_label, format_price_label


router = Router(name="modes-router")

CALLBACK_OPEN_MODES = "open_modes"
CALLBACK_MODE_PREFIX = "mode:"


def build_modes_menu_text(user: dict, runtime_settings: dict, mode_catalog: dict) -> str:
    ui_settings = runtime_settings.get("ui", {})
    limits = runtime_settings.get("limits", {})
    payment_settings = runtime_settings.get("payment", {})
    title = str(ui_settings.get("modes_title") or "Выбери режим общения:").strip()

    parts = [title]
    premium_modes = [
        f"{value.get('icon', '•')} {value.get('name', key)}"
        for key, value in sorted(
            mode_catalog.items(),
            key=lambda item: (
                int(item[1].get("sort_order", 0)),
                str(item[1].get("name") or item[0]).lower(),
            ),
        )
        if bool(value.get("is_premium"))
    ]

    if user.get("is_premium"):
        active_premium_text = str(ui_settings.get("modes_menu_active_premium_text") or "").strip()
        if active_premium_text:
            parts.append(active_premium_text)
        return "\n\n".join(part for part in parts if part)

    access_days = max(1, int(payment_settings.get("access_duration_days", 30)))
    premium_text_template = str(ui_settings.get("modes_menu_premium_text") or "").strip()
    if premium_text_template and premium_modes:
        try:
            parts.append(
                premium_text_template.format(
                    price_label=format_price_label(payment_settings),
                    access_days=access_days,
                    access_days_label=format_access_days_label(access_days),
                    premium_modes_count=len(premium_modes),
                    premium_modes_list=", ".join(premium_modes),
                )
            )
        except (KeyError, ValueError):
            pass

    preview_items = []
    if bool(limits.get("mode_preview_enabled")):
        configured_limits = limits.get("mode_daily_limits", {}) if isinstance(limits, dict) else {}
        for key, value in sorted(
            mode_catalog.items(),
            key=lambda item: (
                int(item[1].get("sort_order", 0)),
                str(item[1].get("name") or item[0]).lower(),
            ),
        ):
            if not bool(value.get("is_premium")):
                continue
            preview_limit = int(configured_limits.get(key, 0) or 0)
            if preview_limit <= 0:
                continue
            preview_items.append(f"{value.get('icon', '•')} {value.get('name', key)} — {preview_limit}/день")

    preview_text_template = str(ui_settings.get("modes_menu_preview_text") or "").strip()
    if preview_text_template and preview_items:
        try:
            parts.append(
                preview_text_template.format(
                    preview_modes_count=len(preview_items),
                    preview_modes_list=", ".join(preview_items),
                )
            )
        except (KeyError, ValueError):
            pass

    return "\n\n".join(part for part in parts if part)


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


@router.callback_query(F.data.startswith(CALLBACK_MODE_PREFIX))
async def change_mode_handler(
    callback: CallbackQuery,
    user_service,
    state_repository,
    admin_settings_service,
    mode_access_service,
    payment_service,
):
    ui_settings = admin_settings_service.get_runtime_settings()["ui"]
    runtime_settings = admin_settings_service.get_runtime_settings()
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
        if callback.message is not None and hasattr(callback.message, "answer"):
            await send_premium_offer(
                callback.message,
                payment_service,
                user_service,
                trigger=OFFER_TRIGGER_MODE_LOCKED,
                mode_name=mode_name,
                premium_limit=int(runtime_settings["limits"].get("premium_daily_messages_limit", 150)),
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
