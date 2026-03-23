import logging

from aiogram import Router
from aiogram.types import Message

from services.ai_service import AIBackpressureError


router = Router()
logger = logging.getLogger(__name__)


@router.message()
async def chat_handler(
    message: Message,
    message_repository,
    ai_service,
    state_repository,
):
    if not message.text:
        await message.answer("I can only respond to text messages.")
        return

    user_id = message.from_user.id
    user_text = message.text

    await message_repository.save(user_id, "user", user_text)

    history = await message_repository.get_last_messages(
        user_id=user_id,
        limit=20,
    )

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
        await message.answer("The bot is busy right now. Please try again in a moment.")
        return
    except Exception:
        logger.exception("AI ERROR")
        await message.answer("I cannot answer right now. Please try again later.")
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
