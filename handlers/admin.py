from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from filters.admin_filter import AdminFilter
from states.admin_states import BroadcastStates, PremiumStates


router = Router()

router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


def is_owner(user_id: int, settings) -> bool:
    return user_id == settings.owner_id


def get_admin_keyboard(is_owner_value: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🛠 Отладка", callback_data="admin_debug")],
        [InlineKeyboardButton(text="❤️ Состояние", callback_data="admin_health")],
        [InlineKeyboardButton(text="👑 Premium", callback_data="admin_premium")],
    ]

    if is_owner_value:
        buttons.append(
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Выдать Premium", callback_data="premium_give")],
            [InlineKeyboardButton(text="➖ Снять Premium", callback_data="premium_remove")],
            [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")],
        ]
    )


def get_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="broadcast_confirm")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")],
        ]
    )


@router.message(Command("admin"))
async def admin_panel(message: Message, settings):
    keyboard = get_admin_keyboard(
        is_owner_value=is_owner(message.from_user.id, settings)
    )
    await message.answer(
        "🔐 Админ-панель\n\nВыбери нужное действие:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery, user_service, message_repository):
    total_users = await user_service.get_total_users()
    premium_users = await user_service.get_premium_users_count()
    total_messages = await message_repository.get_total_messages()
    active_users_by_messages = await message_repository.get_total_users()

    text = (
        "📊 Статистика\n\n"
        f"Всего пользователей: {total_users}\n"
        f"Premium-пользователей: {premium_users}\n"
        f"Пользователей с сообщениями: {active_users_by_messages}\n"
        f"Сообщений в базе: {total_messages}"
    )

    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "admin_debug")
async def admin_debug(callback: CallbackQuery, ai_service, settings):
    stats = ai_service.get_runtime_stats()

    text = (
        "🛠 Отладка\n\n"
        f"DEBUG-режим: {settings.debug}\n"
        f"AI workers запущены: {stats['started']}\n"
        f"Количество workers: {stats['workers']}\n"
        f"Лимит параллельных AI-запросов: {stats['max_parallel_requests']}\n"
        f"Очередь AI: {stats['queue_size']}/{stats['queue_capacity']}\n"
        f"Redis: {settings.redis_url}"
    )

    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "admin_health")
async def admin_health(callback: CallbackQuery, db, redis, ai_service):
    db_status = "ok"
    redis_status = "ok"

    try:
        cursor = await db.connection.execute("SELECT 1")
        await cursor.fetchone()
    except Exception as exc:
        db_status = f"error: {exc}"

    try:
        await redis.ping()
    except Exception as exc:
        redis_status = f"error: {exc}"

    stats = ai_service.get_runtime_stats()
    text = (
        "❤️ Состояние\n\n"
        f"DB: {db_status}\n"
        f"Redis: {redis_status}\n"
        f"AI workers started: {stats['started']}\n"
        f"AI queue: {stats['queue_size']}/{stats['queue_capacity']}"
    )

    await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def broadcast_prompt(callback: CallbackQuery, state: FSMContext, settings):
    if not is_owner(callback.from_user.id, settings):
        await callback.answer("Доступно только владельцу", show_alert=True)
        return

    await state.set_state(BroadcastStates.waiting_for_message)
    await callback.message.answer(
        "📢 Отправь следующим сообщением текст рассылки.\n\n"
        "После этого я покажу подтверждение перед отправкой."
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_for_message)
async def broadcast_prepare(
    message: Message,
    state: FSMContext,
    settings,
):
    if not is_owner(message.from_user.id, settings):
        await state.clear()
        await message.answer("Доступно только владельцу")
        return

    if not message.text or not message.text.strip():
        await message.answer("Текст рассылки не может быть пустым.")
        return

    broadcast_text = message.text.strip()
    await state.update_data(broadcast_text=broadcast_text)
    await state.set_state(BroadcastStates.waiting_for_confirmation)

    preview = broadcast_text
    if len(preview) > 500:
        preview = preview[:500] + "\n\n...<обрезано в preview>"

    await message.answer(
        "📨 Подтверждение рассылки\n\n"
        "Ниже preview сообщения. Подтверди отправку или отмени.\n\n"
        f"{preview}",
        reply_markup=get_broadcast_confirm_keyboard(),
    )


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Рассылка отменена.")
    await callback.answer()


@router.callback_query(F.data == "broadcast_confirm")
async def broadcast_send(
    callback: CallbackQuery,
    state: FSMContext,
    user_service,
    settings,
):
    if not is_owner(callback.from_user.id, settings):
        await state.clear()
        await callback.answer("Доступно только владельцу", show_alert=True)
        return

    data = await state.get_data()
    broadcast_text = data.get("broadcast_text")

    if not broadcast_text:
        await state.clear()
        await callback.message.answer("Не найден текст рассылки. Попробуй заново.")
        await callback.answer()
        return

    user_ids = await user_service.get_all_user_ids()
    sent = 0
    failed = 0

    await callback.answer("Рассылка запущена")

    for user_id in user_ids:
        try:
            await callback.message.bot.send_message(user_id, broadcast_text)
            sent += 1
        except Exception:
            failed += 1

    await state.clear()
    await callback.message.answer(
        "📨 Рассылка завершена\n\n"
        f"Успешно отправлено: {sent}\n"
        f"Ошибок: {failed}\n"
        f"Всего получателей: {len(user_ids)}"
    )


@router.callback_query(F.data == "admin_premium")
async def premium_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "👑 Управление Premium",
        reply_markup=get_premium_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, settings):
    keyboard = get_admin_keyboard(
        is_owner_value=is_owner(callback.from_user.id, settings)
    )

    await callback.message.edit_text(
        "🔐 Админ-панель\n\nВыбери нужное действие:",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "premium_give")
async def premium_give_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PremiumStates.waiting_for_give_user_id)
    await callback.message.answer("➕ Введи `user_id`, чтобы выдать Premium:")
    await callback.answer()


@router.message(PremiumStates.waiting_for_give_user_id)
async def premium_give_handler(
    message: Message,
    state: FSMContext,
    user_service,
    settings,
):
    if not message.text or not message.text.isdigit():
        await message.answer("Введи корректный числовой `user_id`.")
        return

    target_user_id = int(message.text)

    if target_user_id == settings.owner_id:
        await message.answer("Нельзя менять Premium владельцу.")
        await state.clear()
        return

    success = await user_service.set_premium(target_user_id, True)

    if not success:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return

    await message.answer(f"✅ Premium выдан пользователю `{target_user_id}`.")
    await state.clear()


@router.callback_query(F.data == "premium_remove")
async def premium_remove_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PremiumStates.waiting_for_remove_user_id)
    await callback.message.answer("➖ Введи `user_id`, чтобы снять Premium:")
    await callback.answer()


@router.message(PremiumStates.waiting_for_remove_user_id)
async def premium_remove_handler(
    message: Message,
    state: FSMContext,
    user_service,
    settings,
):
    if not message.text or not message.text.isdigit():
        await message.answer("Введи корректный числовой `user_id`.")
        return

    target_user_id = int(message.text)

    if target_user_id == settings.owner_id:
        await message.answer("Нельзя менять Premium владельцу.")
        await state.clear()
        return

    success = await user_service.set_premium(target_user_id, False)

    if not success:
        await message.answer("Пользователь не найден.")
        await state.clear()
        return

    await message.answer(f"✅ Premium снят у пользователя `{target_user_id}`.")
    await state.clear()
