import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery


router = Router(name="payments-router")
logger = logging.getLogger(__name__)
CALLBACK_BUY_PREMIUM = "buy_premium"
OFFER_TRIGGER_DEFAULT = "default"
OFFER_TRIGGER_LIMIT_REACHED = "limit_reached"
OFFER_TRIGGER_MODE_LOCKED = "mode_locked"


def _pick_offer_variant(user_id: int) -> str:
    return "a" if user_id % 2 == 0 else "b"


def _format_price_label(payment_settings: dict) -> str:
    currency = str(payment_settings.get("currency") or "RUB").upper()
    amount_minor_units = int(payment_settings.get("price_minor_units", 0))
    if currency == "XTR":
        return f"{amount_minor_units} {currency}"
    return f"{amount_minor_units / 100:.2f} {currency}"


def _build_offer_intro(
    payment_settings: dict,
    *,
    user_id: int,
    trigger: str,
    mode_name: str | None = None,
    premium_limit: int | None = None,
) -> list[str]:
    variant = _pick_offer_variant(user_id)
    access_days = max(1, int(payment_settings.get("access_duration_days", 30)))
    price_label = _format_price_label(payment_settings)

    cta_text = str(
        payment_settings.get(f"offer_cta_text_{variant}")
        or payment_settings.get("buy_cta_text")
        or ""
    ).strip()
    benefits_text = str(
        payment_settings.get(f"offer_benefits_text_{variant}")
        or payment_settings.get("premium_benefits_text")
        or ""
    ).strip()
    price_line = str(payment_settings.get("offer_price_line_template") or "").strip()
    if price_line:
        price_line = price_line.format(price_label=price_label, access_days=access_days)

    trigger_line = ""
    if trigger == OFFER_TRIGGER_LIMIT_REACHED:
        trigger_line = str(payment_settings.get("offer_limit_reached_template") or "").strip()
        if trigger_line:
            trigger_line = trigger_line.format(
                access_days=access_days,
                premium_limit=premium_limit or 0,
                price_label=price_label,
            )
    elif trigger == OFFER_TRIGGER_MODE_LOCKED:
        trigger_line = str(payment_settings.get("offer_locked_mode_template") or "").strip()
        if trigger_line:
            trigger_line = trigger_line.format(
                mode_name=mode_name or "Premium",
                access_days=access_days,
                premium_limit=premium_limit or 0,
                price_label=price_label,
            )

    return [part for part in (trigger_line, cta_text, price_line, benefits_text) if part]


async def send_premium_offer(
    message: Message,
    payment_service,
    user_service=None,
    *,
    trigger: str = OFFER_TRIGGER_DEFAULT,
    mode_name: str | None = None,
    premium_limit: int | None = None,
) -> bool:
    payment_settings = payment_service.get_payment_settings()
    if not payment_service.is_enabled():
        await message.answer(payment_settings["unavailable_message"])
        return False

    status_text = ""
    if user_service is not None:
        user = await user_service.get_user(message.from_user.id)
        status_text = payment_service.build_subscription_status_text(user)

    intro_parts = []
    if status_text:
        intro_parts.append(status_text)
    intro_parts.extend(
        _build_offer_intro(
            payment_settings,
            user_id=message.from_user.id,
            trigger=trigger,
            mode_name=mode_name,
            premium_limit=premium_limit,
        )
    )

    if intro_parts:
        await message.answer("\n\n".join(intro_parts))

    sent = await payment_service.send_premium_invoice(message)
    if not sent:
        await message.answer(payment_settings["invoice_error_message"])
        return False

    return True


@router.message(Command("buy"))
async def buy_premium(message: Message, payment_service, user_service):
    await user_service.ensure_user(message.from_user)
    await send_premium_offer(message, payment_service, user_service)


@router.callback_query(F.data == CALLBACK_BUY_PREMIUM)
async def buy_premium_callback(callback, payment_service, user_service):
    await user_service.ensure_user(callback.from_user)
    await callback.answer()

    if callback.message is None or not hasattr(callback.message, "answer"):
        return

    await send_premium_offer(callback.message, payment_service, user_service)


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery, bot, payment_service):
    is_valid = payment_service.validate_invoice_payload(
        pre_checkout_query.invoice_payload,
        pre_checkout_query.from_user.id,
    )
    await bot.answer_pre_checkout_query(
        pre_checkout_query.id,
        ok=is_valid,
        error_message=None if is_valid else "Некорректный платежный запрос.",
    )


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, payment_service, user_service):
    await user_service.ensure_user(message.from_user)
    try:
        result = await payment_service.handle_successful_payment(message)
    except ValueError:
        logger.warning("Rejected successful_payment with invalid payload for user %s", message.from_user.id)
        return

    await message.answer(payment_service.build_success_message(result))
    if result and result.get("referral"):
        referral_settings = payment_service.referral_service.get_settings()
        referrer_id = result["referral"]["referrer_user_id"]
        try:
            await message.bot.send_message(referrer_id, referral_settings["referrer_reward_message"])
        except Exception:
            pass
