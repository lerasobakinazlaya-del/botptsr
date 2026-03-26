from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery


router = Router(name="payments-router")


async def send_premium_offer(message: Message, payment_service) -> bool:
    payment_settings = payment_service.get_payment_settings()
    if not payment_service.is_enabled():
        await message.answer(payment_settings["unavailable_message"])
        return False

    benefits_text = str(payment_settings.get("premium_benefits_text") or "").strip()
    buy_cta_text = str(payment_settings.get("buy_cta_text") or "").strip()
    if benefits_text or buy_cta_text:
        intro_parts = []
        if buy_cta_text:
            intro_parts.append(buy_cta_text)
        if benefits_text:
            intro_parts.append(benefits_text)
        await message.answer("\n\n".join(intro_parts))

    sent = await payment_service.send_premium_invoice(message)
    if not sent:
        await message.answer(payment_settings["invoice_error_message"])
        return False

    return True


@router.message(Command("buy"))
async def buy_premium(message: Message, payment_service):
    await send_premium_offer(message, payment_service)


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery, bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, payment_service):
    result = await payment_service.handle_successful_payment(message)
    payment_settings = payment_service.get_payment_settings()
    await message.answer(payment_settings["success_message"])
    if result and result.get("referral"):
        referral_settings = payment_service.referral_service.get_settings()
        referrer_id = result["referral"]["referrer_user_id"]
        try:
            await message.bot.send_message(referrer_id, referral_settings["referrer_reward_message"])
        except Exception:
            pass
