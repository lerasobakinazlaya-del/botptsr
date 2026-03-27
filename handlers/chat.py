import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from config.modes import get_mode
from handlers.modes import show_modes_menu
from handlers.payments import send_premium_offer
from services.ai_profile_service import resolve_ai_profile
from services.ai_service import AIBackpressureError
from services.telegram_formatting import (
    TelegramFormattingOptions,
    escape_plain_text_for_telegram,
    format_model_response_for_telegram,
)


router = Router()
logger = logging.getLogger(__name__)


def _proactive_help_text() -> str:
    return (
        "Команды инициативности:\n"
        "/proactive - показать статус\n"
        "/proactive on - бот может иногда писать первым\n"
        "/proactive off - отключить инициативные сообщения\n"
        "/quiet - быстрый тихий режим\n"
        "/quiet off - вернуть инициативные сообщения"
    )


def _set_proactive_enabled(state: dict, enabled: bool) -> dict:
    updated = dict(state or {})
    proactive_preferences = dict(updated.get("proactive_preferences") or {})
    proactive_preferences["enabled"] = bool(enabled)
    proactive_preferences["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated["proactive_preferences"] = proactive_preferences
    return updated


def _set_user_timezone(state: dict, timezone_name: str | None) -> dict:
    updated = dict(state or {})
    proactive_preferences = dict(updated.get("proactive_preferences") or {})
    proactive_preferences["timezone"] = timezone_name
    proactive_preferences["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated["proactive_preferences"] = proactive_preferences
    return updated


async def _handle_timezone_command(message: Message, user_preference_repository, state_repository) -> bool:
    raw_text = (message.text or "").strip()
    command, _, argument = raw_text.partition(" ")
    if command.lower() != "/timezone":
        return False

    state = await state_repository.get(message.from_user.id)
    proactive_preferences = await user_preference_repository.get_preferences(
        message.from_user.id,
        fallback=state.get("proactive_preferences"),
    )
    current_timezone = str(proactive_preferences.get("timezone") or "").strip()
    normalized_argument = argument.strip()

    if not normalized_argument:
        await message.answer(
            "Текущая timezone: "
            + (current_timezone or "не задана, используется общая timezone бота.")
            + "\n\nПример: /timezone Europe/Moscow"
        )
        return True

    if normalized_argument.lower() in {"off", "reset", "default"}:
        new_state = _set_user_timezone(state, None)
        await state_repository.save(message.from_user.id, new_state)
        await user_preference_repository.set_timezone(message.from_user.id, None)
        await message.answer("Личная timezone сброшена. Теперь используется общая timezone бота.")
        return True

    try:
        ZoneInfo(normalized_argument)
    except Exception:
        await message.answer(
            "Не смог распознать timezone.\n\n"
            "Используй формат вроде Europe/Moscow, Europe/Berlin или America/New_York."
        )
        return True

    new_state = _set_user_timezone(state, normalized_argument)
    await state_repository.save(message.from_user.id, new_state)
    await user_preference_repository.set_timezone(message.from_user.id, normalized_argument)
    await message.answer(f"Timezone сохранена: {normalized_argument}")
    return True


async def _handle_proactive_command(message: Message, user_preference_repository, state_repository) -> bool:
    raw_text = (message.text or "").strip()
    command, _, argument = raw_text.partition(" ")
    command = command.lower()
    argument = argument.strip().lower()

    if command not in {"/proactive", "/quiet"}:
        return False

    state = await state_repository.get(message.from_user.id)
    proactive_preferences = await user_preference_repository.get_preferences(
        message.from_user.id,
        fallback=state.get("proactive_preferences"),
    )
    is_enabled = bool(proactive_preferences.get("proactive_enabled", True))

    if command == "/quiet":
        if argument in {"", "on"}:
            new_state = _set_proactive_enabled(state, False)
            await state_repository.save(message.from_user.id, new_state)
            await user_preference_repository.set_proactive_enabled(message.from_user.id, False)
            await message.answer(
                "Тихий режим включён. Я не буду писать первой, пока ты сам снова это не разрешишь.\n\n"
                "Вернуть можно командой /proactive on или /quiet off."
            )
            return True
        if argument == "off":
            new_state = _set_proactive_enabled(state, True)
            await state_repository.save(message.from_user.id, new_state)
            await user_preference_repository.set_proactive_enabled(message.from_user.id, True)
            await message.answer("Тихий режим выключен. Если диалог подходящий, я снова смогу иногда написать первой.")
            return True
        await message.answer(_proactive_help_text())
        return True

    if argument in {"", "status"}:
        await message.answer(
            "Статус инициативных сообщений: "
            + ("включены." if is_enabled else "выключены.")
            + "\n\n"
            + _proactive_help_text()
        )
        return True
    if argument == "on":
        new_state = _set_proactive_enabled(state, True)
        await state_repository.save(message.from_user.id, new_state)
        await user_preference_repository.set_proactive_enabled(message.from_user.id, True)
        await message.answer("Инициативные сообщения включены. Я смогу иногда аккуратно напомнить о себе.")
        return True
    if argument == "off":
        new_state = _set_proactive_enabled(state, False)
        await state_repository.save(message.from_user.id, new_state)
        await user_preference_repository.set_proactive_enabled(message.from_user.id, False)
        await message.answer("Инициативные сообщения отключены. Буду писать только когда ты сам напишешь.")
        return True

    await message.answer(_proactive_help_text())
    return True


@router.message()
async def chat_handler(
    message: Message,
    message_repository,
    ai_service,
    long_term_memory_service,
    state_repository,
    user_preference_repository,
    payment_service,
    user_service,
    referral_service,
    admin_settings_service,
    conversation_summary_service,
    mode_access_service,
    db,
):
    runtime_settings = admin_settings_service.get_runtime_settings()
    ai_settings = runtime_settings["ai"]
    chat_settings = runtime_settings["chat"]
    ui_settings = runtime_settings["ui"]
    limits_settings = runtime_settings["limits"]
    referral_settings = runtime_settings["referral"]
    mode_catalog = admin_settings_service.get_mode_catalog()

    if not message.text:
        await message.answer(chat_settings["non_text_message"])
        return

    user_id = message.from_user.id
    user_text = message.text.strip()
    user = await user_service.get_user(user_id)
    if user is None and message.from_user is not None:
        await user_service.ensure_user(message.from_user)
        user = await user_service.get_user(user_id)

    if user_text == ui_settings["write_button_text"]:
        await message.answer(chat_settings["write_prompt_message"])
        return

    if await _handle_proactive_command(message, user_preference_repository, state_repository):
        return
    if await _handle_timezone_command(message, user_preference_repository, state_repository):
        return

    if user_text == ui_settings["modes_button_text"]:
        await show_modes_menu(message, user_service, admin_settings_service)
        return

    if user_text == ui_settings["premium_button_text"]:
        await send_premium_offer(message, payment_service)
        return

    if user_text.lower() in {"/ref", "рефералка", "реферальная ссылка"} and referral_settings["enabled"]:
        me = await message.bot.get_me()
        ref_link = f"https://t.me/{me.username}?start={referral_settings['start_parameter_prefix']}{user_id}"
        share_text = referral_settings["share_text_template"].replace("{ref_link}", ref_link)
        await message.answer(
            f"{referral_settings['program_title']}\n\n"
            f"{referral_settings['program_description']}\n\n"
            f"{share_text}"
        )
        return

    limits_bypass_for_admins = limits_settings.get("admins_bypass_daily_limits", True)
    should_apply_limits = user is not None and (
        not user.get("is_admin") or not limits_bypass_for_admins
    )

    if should_apply_limits:
        today_count = await message_repository.get_user_messages_count_today(user_id)

        if user.get("is_premium"):
            if (
                limits_settings.get("premium_daily_messages_enabled")
                and today_count >= limits_settings["premium_daily_messages_limit"]
            ):
                await message.answer(limits_settings["premium_daily_limit_message"])
                return
        elif (
            limits_settings["free_daily_messages_enabled"]
            and today_count >= limits_settings["free_daily_messages_limit"]
        ):
            await message.answer(limits_settings["free_daily_limit_message"])
            return

    state = await state_repository.get(user_id)
    logger.debug("[STATE] Loaded for user %s", user_id)
    active_mode = str(state.get("active_mode") or (user or {}).get("active_mode") or "base")
    ai_profile = resolve_ai_profile(ai_settings, active_mode)
    selection_status = mode_access_service.get_selection_status(
        user=user or {},
        mode_key=active_mode,
        state=state,
        runtime_settings=runtime_settings,
        mode_catalog=mode_catalog,
    )

    if not selection_status["allowed"]:
        mode = get_mode(active_mode)
        await message.answer(
            limits_settings["mode_preview_exhausted_message"].format(
                mode_name=mode.name,
                daily_limit=selection_status["daily_limit"],
            )
        )
        return

    history = await message_repository.get_last_messages(
        user_id=user_id,
        limit=ai_profile["history_message_limit"],
    )

    if chat_settings["typing_action_enabled"]:
        await message.bot.send_chat_action(user_id, "typing")

    async def remember_user_message() -> None:
        try:
            await long_term_memory_service.capture_from_message(user_id, user_text)
        except Exception:
            logger.exception("LONG TERM MEMORY ERROR")

    try:
        result = await ai_service.generate_response(
            user_id=user_id,
            history=history,
            user_message=user_text,
            state=state,
        )
    except AIBackpressureError:
        await message_repository.save(user_id, "user", user_text)
        await remember_user_message()
        await message.answer(chat_settings["busy_message"])
        return
    except Exception:
        logger.exception("AI ERROR")
        await message_repository.save(user_id, "user", user_text)
        await remember_user_message()
        await message.answer(chat_settings["ai_error_message"])
        return

    response = result.response
    new_state = result.new_state

    if new_state is None:
        logger.warning(
            "[STATE] AI returned None for user %s, keeping previous state",
            user_id,
        )
        new_state = state

    response_mode = str(new_state.get("adaptive_mode") or new_state.get("active_mode") or active_mode)
    mode_config = admin_settings_service.get_modes().get(response_mode, {})
    formatting_options = TelegramFormattingOptions(
        allow_bold=bool(mode_config.get("allow_bold", False)),
        allow_italic=bool(mode_config.get("allow_italic", False)),
    )
    formatted_response = format_model_response_for_telegram(response, formatting_options)

    try:
        new_state = mode_access_service.register_successful_message(
            new_state,
            mode_key=active_mode,
            user=user or {},
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        async with db.transaction():
            await message_repository.save(user_id, "user", user_text, commit=False)
            await state_repository.save(user_id, new_state, commit=False)
            await message_repository.save(user_id, "assistant", response, commit=False)
    except Exception:
        logger.exception("DB ERROR while saving chat exchange")
        await message.answer(chat_settings["ai_error_message"])
        return

    await remember_user_message()

    try:
        conversation_summary_service.schedule_refresh(user_id, new_state)
    except Exception:
        logger.exception("SUMMARY SCHEDULER ERROR")

    try:
        await message.answer(formatted_response or escape_plain_text_for_telegram(response))
    except TelegramBadRequest:
        logger.exception("TELEGRAM FORMAT ERROR")
        await message.answer(escape_plain_text_for_telegram(response))
