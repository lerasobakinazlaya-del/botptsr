import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from handlers.modes import show_modes_menu
from handlers.payments import send_premium_offer
from services.ai_service import AIBackpressureError
from services.telegram_formatting import (
    TelegramFormattingOptions,
    escape_plain_text_for_telegram,
    format_model_response_for_telegram,
)


router = Router()
logger = logging.getLogger(__name__)


@router.message()
async def chat_handler(
    message: Message,
    message_repository,
    ai_service,
    long_term_memory_service,
    state_repository,
    payment_service,
    user_service,
    referral_service,
    admin_settings_service,
    conversation_summary_service,
    db,
):
    runtime_settings = admin_settings_service.get_runtime_settings()
    ai_settings = runtime_settings["ai"]
    chat_settings = runtime_settings["chat"]
    ui_settings = runtime_settings["ui"]
    limits_settings = runtime_settings["limits"]
    referral_settings = runtime_settings["referral"]

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

    history = await message_repository.get_last_messages(
        user_id=user_id,
        limit=ai_settings["history_message_limit"],
    )

    if chat_settings["typing_action_enabled"]:
        await message.bot.send_chat_action(user_id, "typing")

    state = await state_repository.get(user_id)
    logger.debug("[STATE] Loaded for user %s", user_id)

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

    active_mode = str(new_state.get("active_mode") or "base")
    mode_config = admin_settings_service.get_modes().get(active_mode, {})
    formatting_options = TelegramFormattingOptions(
        allow_bold=bool(mode_config.get("allow_bold", False)),
        allow_italic=bool(mode_config.get("allow_italic", False)),
    )
    formatted_response = format_model_response_for_telegram(response, formatting_options)

    try:
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
