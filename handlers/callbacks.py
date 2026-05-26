import logging

from aiogram import Router
from aiogram.types import CallbackQuery


router = Router(name="callback-safety-router")
logger = logging.getLogger(__name__)


@router.callback_query()
async def unknown_callback_handler(callback: CallbackQuery):
    """Answer stale inline buttons locally so they never look like chat input."""
    logger.info(
        "Unhandled callback query: user_id=%s data=%r",
        getattr(callback.from_user, "id", None),
        callback.data,
    )
    await callback.answer("Кнопка устарела. Открой меню заново.", show_alert=False)
