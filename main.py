import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from config.settings import get_settings
from core.container import Container
from core.logger import setup_logger
from core.middlewares import (
    LoggingMiddleware,
    MessageSizeMiddleware,
    SuspiciousContentMiddleware,
    ThrottlingMiddleware,
)
from handlers import admin, chat, modes, payments, start


@asynccontextmanager
async def lifespan(container: Container):
    logging.info("Connecting to database...")
    await container.db.connect()

    logging.info("Initializing tables...")
    await container.user_service.init_table()
    await container.state_repository.init_table()

    logging.info("Starting AI workers...")
    await container.ai_service.start()

    try:
        yield
    finally:
        logging.info("Stopping reengagement worker...")
        await container.reengagement_service.stop()

        logging.info("Stopping AI workers...")
        await container.ai_service.close()

        logging.info("Closing OpenAI client...")
        await container.openai_client.close()

        logging.info("Closing FSM storage...")
        await container.fsm_storage.close()

        if container.redis is not None:
            logging.info("Closing Redis connection...")
            await container.redis.aclose()

        logging.info("Closing database connection...")
        await container.db.close()


def create_dispatcher(container: Container, settings) -> Dispatcher:
    dp = Dispatcher(storage=container.fsm_storage)

    dp["settings"] = settings
    dp["ai_service"] = container.ai_service
    dp["user_service"] = container.user_service
    dp["message_repository"] = container.message_repository
    dp["payment_service"] = container.payment_service
    dp["payment_repository"] = container.payment_repository
    dp["referral_service"] = container.referral_service
    dp["state_repository"] = container.state_repository
    dp["db"] = container.db
    dp["redis"] = container.redis
    dp["admin_settings_service"] = container.admin_settings_service
    dp["mode_access_service"] = container.mode_access_service

    dp.message.middleware(LoggingMiddleware())
    dp.message.middleware(
        ThrottlingMiddleware(
            redis=container.redis,
            settings_service=container.admin_settings_service,
        )
    )
    dp.message.middleware(MessageSizeMiddleware(settings_service=container.admin_settings_service))
    dp.message.middleware(SuspiciousContentMiddleware(settings_service=container.admin_settings_service))

    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(payments.router)
    dp.include_router(modes.router)
    dp.include_router(chat.router)

    return dp


async def main():
    settings = get_settings()
    setup_logger(debug=settings.debug)

    container = Container(settings)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        dp = create_dispatcher(container, settings)

        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except TelegramNetworkError as exc:
            logging.warning("Failed to delete webhook before startup: %s", exc)

        async with lifespan(container):
            await container.reengagement_service.start(bot)
            logging.info("Bot started")
            try:
                await dp.start_polling(bot)
            except TelegramNetworkError as exc:
                logging.warning("Polling stopped due to Telegram network error: %s", exc)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")
