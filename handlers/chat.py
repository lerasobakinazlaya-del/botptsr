import logging

from aiogram import Router
from aiogram.types import Message

from handlers.modes import show_modes_menu
from handlers.payments import send_premium_offer
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
    admin_settings_service,
):
    runtime_settings = admin_settings_service.get_runtime_settings()
    ai_settings = runtime_settings["ai"]
    chat_settings = runtime_settings["chat"]
    ui_settings = runtime_settings["ui"]

    if not message.text:
        await message.answer(chat_settings["non_text_message"])
        return

    user_id = message.from_user.id
    user_text = message.text.strip()

    if user_text == ui_settings["write_button_text"]:
        await message.answer("Я рядом. Напиши, что у тебя на уме.")
        return

    if user_text == ui_settings["modes_button_text"]:
        await show_modes_menu(message, user_service, admin_settings_service)
        return

    if user_text == ui_settings["premium_button_text"]:
        await send_premium_offer(message, payment_service)
        return

    await message_repository.save(user_id, "user", user_text)

    history = await message_repository.get_last_messages(
        user_id=user_id,
        limit=ai_settings["history_message_limit"],
    )

    if chat_settings["typing_action_enabled"]:
        await message.bot.send_chat_action(user_id, "typing")

    state = await state_repository.get(user_id)
    logger.debug("[STATE] Loaded for user %s", user_id)

    try:
        result = await ai_service.generate_response(
            user_id=user_id,
            history=history,
            user_message=user_text,
            state=state,
        )
    except AIBackpressureError:
        await message.answer(chat_settings["busy_message"])
        return
    except Exception:
        logger.exception("AI ERROR")
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

    await state_repository.save(user_id, new_state)
    await message_repository.save(user_id, "assistant", response)
    await message.answer(response)
