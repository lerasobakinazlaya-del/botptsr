import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery
from aiogram.exceptions import TelegramBadRequest

from services.payment_formatting import format_access_days_label, format_price_label


router = Router(name="payments-router")
logger = logging.getLogger(__name__)
CALLBACK_OPEN_PREMIUM_MENU = "open_premium_menu"
CALLBACK_BUY_PREMIUM = "buy_premium"
CALLBACK_PREMIUM_BACK_TO_MODES = "premium_back_to_modes"
OFFER_TRIGGER_DEFAULT = "default"
OFFER_TRIGGER_LIMIT_REACHED = "limit_reached"
OFFER_TRIGGER_MODE_LOCKED = "mode_locked"
OFFER_TRIGGER_PREVIEW_EXHAUSTED = "preview_exhausted"

SUPPORTED_OFFER_TRIGGERS = {
    OFFER_TRIGGER_DEFAULT,
    OFFER_TRIGGER_LIMIT_REACHED,
    OFFER_TRIGGER_MODE_LOCKED,
    OFFER_TRIGGER_PREVIEW_EXHAUSTED,
}


def _pick_offer_variant(user_id: int) -> str:
    return "a" if user_id % 2 == 0 else "b"


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
    price_label = format_price_label(payment_settings)

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
                mode_name=mode_name or "премиум",
                access_days=access_days,
                premium_limit=premium_limit or 0,
                price_label=price_label,
            )
    elif trigger == OFFER_TRIGGER_PREVIEW_EXHAUSTED:
        trigger_line = str(
            payment_settings.get("offer_preview_exhausted_template")
            or payment_settings.get("offer_locked_mode_template")
            or ""
        ).strip()
        if trigger_line:
            trigger_line = trigger_line.format(
                mode_name=mode_name or "Режим",
                access_days=access_days,
                premium_limit=premium_limit or 0,
                price_label=price_label,
            )

    return [part for part in (trigger_line, cta_text, price_line, benefits_text) if part]


def _normalize_offer_trigger(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SUPPORTED_OFFER_TRIGGERS else OFFER_TRIGGER_DEFAULT


def _build_buy_premium_callback_data(trigger: str) -> str:
    normalized_trigger = _normalize_offer_trigger(trigger)
    if normalized_trigger == OFFER_TRIGGER_DEFAULT:
        return CALLBACK_BUY_PREMIUM
    return f"{CALLBACK_BUY_PREMIUM}:{normalized_trigger}"


def _parse_buy_premium_callback_data(data: str | None) -> str:
    raw = str(data or "").strip()
    if raw == CALLBACK_BUY_PREMIUM:
        return OFFER_TRIGGER_DEFAULT
    prefix = f"{CALLBACK_BUY_PREMIUM}:"
    if raw.startswith(prefix):
        return _normalize_offer_trigger(raw[len(prefix):])
    return OFFER_TRIGGER_DEFAULT


def _build_premium_menu_keyboard(payment_settings: dict, *, trigger: str) -> InlineKeyboardMarkup:
    price_label = format_price_label(payment_settings)
    access_days = max(1, int(payment_settings.get("access_duration_days", 30)))
    access_days_label = format_access_days_label(access_days)
    buy_template = str(payment_settings.get("premium_menu_buy_button_template") or "").strip()
    if buy_template:
        try:
            buy_text = buy_template.format(
                price_label=price_label,
                access_days=access_days,
                access_days_label=access_days_label,
            ).strip()
        except (KeyError, ValueError):
            buy_text = ""
    else:
        buy_text = ""
    buy_text = buy_text or str(payment_settings.get("buy_cta_text") or "Оформить Premium").strip()
    back_text = str(payment_settings.get("premium_menu_back_button_text") or "← К режимам").strip() or "← К режимам"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=buy_text, callback_data=_build_buy_premium_callback_data(trigger))],
            [InlineKeyboardButton(text=back_text, callback_data=CALLBACK_PREMIUM_BACK_TO_MODES)],
        ]
    )


def _sorted_modes(mode_catalog: dict | None) -> list[tuple[str, dict]]:
    if not isinstance(mode_catalog, dict):
        return []

    return sorted(
        mode_catalog.items(),
        key=lambda item: (
            int(item[1].get("sort_order", 0)),
            str(item[1].get("name") or item[0]).lower(),
        ),
    )


def _build_premium_menu_details(
    runtime_settings: dict | None,
    mode_catalog: dict | None,
    *,
    user_is_premium: bool,
) -> list[str]:
    if not isinstance(runtime_settings, dict):
        return []

    payment_settings = runtime_settings.get("payment", {})
    limits = runtime_settings.get("limits", {})
    price_label = format_price_label(payment_settings)
    access_days = max(1, int(payment_settings.get("access_duration_days", 30)))
    access_days_label = format_access_days_label(access_days)
    premium_daily_limit = max(1, int(limits.get("premium_daily_messages_limit", 150)))

    premium_modes = [
        f"{value.get('icon', '•')} {value.get('name', key)}"
        for key, value in _sorted_modes(mode_catalog)
        if bool(value.get("is_premium"))
    ]
    preview_modes: list[str] = []
    if not user_is_premium and bool(limits.get("mode_preview_enabled")):
        configured_limits = limits.get("mode_daily_limits", {}) if isinstance(limits, dict) else {}
        default_limit = max(0, int(limits.get("mode_preview_default_limit", 0) or 0))
        for key, value in _sorted_modes(mode_catalog):
            if not bool(value.get("is_premium")):
                continue
            try:
                preview_limit = max(0, int(configured_limits.get(key, default_limit)))
            except (TypeError, ValueError):
                preview_limit = default_limit
            if preview_limit <= 0:
                continue
            preview_modes.append(f"{value.get('icon', '•')} {value.get('name', key)} — {preview_limit}/день")

    details: list[str] = []
    description_template = str(payment_settings.get("premium_menu_description_template") or "").strip()
    if description_template and premium_modes:
        try:
            details.append(
                description_template.format(
                    price_label=price_label,
                    access_days=access_days,
                    access_days_label=access_days_label,
                    premium_daily_limit=premium_daily_limit,
                    premium_modes_count=len(premium_modes),
                    premium_modes_list=", ".join(premium_modes),
                )
            )
        except (KeyError, ValueError):
            pass

    preview_template = str(payment_settings.get("premium_menu_preview_template") or "").strip()
    if preview_template and preview_modes:
        try:
            details.append(
                preview_template.format(
                    preview_modes_count=len(preview_modes),
                    preview_modes_list=", ".join(preview_modes),
                )
            )
        except (KeyError, ValueError):
            pass

    return details


async def show_premium_menu(
    message: Message,
    payment_service,
    user_service=None,
    admin_settings_service=None,
    *,
    trigger: str = OFFER_TRIGGER_DEFAULT,
    mode_name: str | None = None,
    premium_limit: int | None = None,
    edit_current: bool = False,
) -> bool:
    payment_settings = payment_service.get_payment_settings()
    if not payment_service.is_enabled():
        await message.answer(payment_settings["unavailable_message"])
        return False

    status_text = ""
    offer_variant = payment_service.get_offer_variant(message.from_user.id)
    runtime_settings = None
    mode_catalog = None
    if user_service is not None:
        user = await user_service.get_user(message.from_user.id)
        status_text = payment_service.build_subscription_status_text(user)
    else:
        user = None

    if admin_settings_service is not None:
        runtime_settings = admin_settings_service.get_runtime_settings()
        runtime_settings = {
            **runtime_settings,
            "payment": payment_settings,
        }
        mode_catalog = admin_settings_service.get_mode_catalog()

    text_parts = []
    if status_text:
        text_parts.append(status_text)
    text_parts.extend(
        _build_offer_intro(
            payment_settings,
            user_id=message.from_user.id,
            trigger=trigger,
            mode_name=mode_name,
            premium_limit=premium_limit,
            )
        )
    text_parts.extend(
        _build_premium_menu_details(
            runtime_settings,
            mode_catalog,
            user_is_premium=bool((user or {}).get("is_premium")),
        )
    )
    text = "\n\n".join(part for part in text_parts if part).strip() or str(payment_settings.get("product_description") or "").strip()
    reply_markup = _build_premium_menu_keyboard(payment_settings, trigger=trigger)

    if edit_current and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=reply_markup)
        except TelegramBadRequest:
            await message.answer(text, reply_markup=reply_markup)
    else:
        await message.answer(text, reply_markup=reply_markup)

    await payment_service.track_offer_shown(
        user_id=message.from_user.id,
        trigger=trigger,
        variant=offer_variant,
        metadata={
            "mode_name": mode_name,
            "premium_limit": premium_limit,
        },
    )
    return True


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

    sent = await payment_service.send_premium_invoice(message)
    if not sent:
        await message.answer(payment_settings["invoice_error_message"])
        return False

    await payment_service.track_invoice_opened(
        user_id=message.from_user.id,
        trigger=trigger,
        variant=payment_service.get_offer_variant(message.from_user.id),
        metadata={
            "mode_name": mode_name,
            "premium_limit": premium_limit,
        },
    )
    return True


@router.message(Command("buy"))
async def buy_premium(message: Message, payment_service, user_service, admin_settings_service):
    await user_service.ensure_user(message.from_user)
    await show_premium_menu(message, payment_service, user_service, admin_settings_service)


@router.callback_query(F.data == CALLBACK_OPEN_PREMIUM_MENU)
async def open_premium_menu_callback(callback: CallbackQuery, payment_service, user_service, admin_settings_service):
    await user_service.ensure_user(callback.from_user)
    await callback.answer()

    if callback.message is None:
        return

    await show_premium_menu(
        callback.message,
        payment_service,
        user_service,
        admin_settings_service,
        edit_current=True,
    )


@router.callback_query(F.data.startswith(CALLBACK_BUY_PREMIUM))
async def buy_premium_callback(callback: CallbackQuery, payment_service, user_service):
    await user_service.ensure_user(callback.from_user)
    await callback.answer()

    if callback.message is None or not hasattr(callback.message, "answer"):
        return

    await send_premium_offer(
        callback.message,
        payment_service,
        user_service,
        trigger=_parse_buy_premium_callback_data(callback.data),
    )


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
