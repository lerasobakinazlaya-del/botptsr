from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery


router = Router(name="payments-router")

PREMIUM_BUTTON_TEXT = "💎 Premium"


@router.message(Command("buy"))
@router.message(F.text == PREMIUM_BUTTON_TEXT)
async def buy_premium(message: Message, payment_service):
    if not payment_service.is_enabled():
        await message.answer(
            "Оплата пока не настроена. Обратись к администратору."
        )
        return

    sent = await payment_service.send_premium_invoice(message)
    if not sent:
        await message.answer(
            "Не удалось создать счет. Попробуй позже."
        )


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery, bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, payment_service):
    await payment_service.handle_successful_payment(message)
    await message.answer(
        "Оплата прошла успешно. Premium уже активирован."
    )
