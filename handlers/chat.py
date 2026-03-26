import logging

from aiogram import Router
from aiogram.types import Message

from config.modes import get_mode
from handlers.modes import show_modes_menu
from handlers.payments import send_premium_offer
from services.ai_profile_service import resolve_ai_profile
from services.ai_service import AIBackpressureError


router = Router()
logger = logging.getLogger(__name__)


@router.message()
async def chat_handler(
    message: Message,
    message_repository,
    ai_service,
    state_repository,
    payment_service,
    user_service,
    referral_service,
    admin_settings_service,
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

    if (
        user
        and not user.get("is_premium")
        and limits_settings["free_daily_messages_enabled"]
    ):
        today_count = await message_repository.get_user_messages_count_today(user_id)
        if today_count >= limits_settings["free_daily_messages_limit"]:
            await message.answer(limits_settings["free_daily_limit_message"])
            return

    if chat_settings["typing_action_enabled"]:
        await message.bot.send_chat_action(user_id, "typing")

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

    try:
        result = await ai_service.generate_response(
            user_id=user_id,
            history=history,
            user_message=user_text,
            state=state,
        )
    except AIBackpressureError:
        await message_repository.save(user_id, "user", user_text)
        await message.answer(chat_settings["busy_message"])
        return
    except Exception:
        logger.exception("AI ERROR")
        await message_repository.save(user_id, "user", user_text)
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

    await message.answer(response)
