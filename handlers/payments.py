import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery

from services.payment_formatting import format_access_days_label, format_package_price_label


router = Router(name="payments-router")
logger = logging.getLogger(__name__)
CALLBACK_OPEN_PREMIUM_MENU = "open_premium_menu"
CALLBACK_BUY_PREMIUM = "buy_premium"
CALLBACK_CONFIRM_VIRTUAL_PAYMENT = "confirm_virtual_payment"
CALLBACK_PREMIUM_BACK_TO_MODES = "premium_back_to_modes"
OFFER_TRIGGER_DEFAULT = "default"
OFFER_TRIGGER_LIMIT_REACHED = "limit_reached"
OFFER_TRIGGER_MODE_LOCKED = "mode_locked"
OFFER_TRIGGER_PREVIEW_EXHAUSTED = "preview_exhausted"
OFFER_TRIGGER_EMOTIONAL_ENGAGEMENT = "emotional_engagement"
OFFER_TRIGGER_USEFUL_ADVICE = "useful_advice"

SUPPORTED_OFFER_TRIGGERS = {
    OFFER_TRIGGER_DEFAULT,
    OFFER_TRIGGER_LIMIT_REACHED,
    OFFER_TRIGGER_MODE_LOCKED,
    OFFER_TRIGGER_PREVIEW_EXHAUSTED,
    OFFER_TRIGGER_EMOTIONAL_ENGAGEMENT,
    OFFER_TRIGGER_USEFUL_ADVICE,
}


def _pick_offer_variant(user_id: int) -> str:
    return "a" if user_id % 2 == 0 else "b"


def _normalize_offer_trigger(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SUPPORTED_OFFER_TRIGGERS else OFFER_TRIGGER_DEFAULT


def _build_offer_teaser(trigger: str, mode_name: str | None = None) -> str:
    normalized_mode = str(mode_name or "").strip().lower()
    if trigger == OFFER_TRIGGER_LIMIT_REACHED:
        return "Не хочу рвать это здесь. В Premium я продолжаю без обрыва, сушняка и урезанного темпа."
    if trigger == OFFER_TRIGGER_EMOTIONAL_ENGAGEMENT:
        return "Похоже, здесь тебе важен не разовый ответ, а опора, которая помнит контекст и может идти глубже."
    if trigger == OFFER_TRIGGER_USEFUL_ADVICE:
        return "Я могу продолжить это глубже: с более длинным разбором, памятью контекста и без обрыва на самом полезном месте."

    if "доминир" in normalized_mode or "жестк" in normalized_mode or "фокус" in normalized_mode:
        return "Если хочешь, я продолжу жёстче, увереннее и с более собранным темпом."
    if "наставник" in normalized_mode or "разбор" in normalized_mode or "mentor" in normalized_mode:
        return "Если хочешь, я соберу это в более точную и сильную линию без воды."
    if "психолог" in normalized_mode or "comfort" in normalized_mode:
        return "Если хочешь, я пойду глубже, бережнее и точнее, без поверхностных ответов."

    if trigger in {OFFER_TRIGGER_MODE_LOCKED, OFFER_TRIGGER_PREVIEW_EXHAUSTED}:
        return "Если хочешь, я продолжу в этом голосе дальше, глубже и без обрыва после пробного касания."
    return ""


def _build_offer_intro(
    payment_settings: dict,
    primary_package: dict | None,
    *,
    user_id: int,
    trigger: str,
    mode_name: str | None = None,
    premium_limit: int | None = None,
) -> list[str]:
    variant = _pick_offer_variant(user_id)
    package = primary_package or {}
    access_days = max(1, int(package.get("access_duration_days", payment_settings.get("access_duration_days", 30))))
    price_label = format_package_price_label(package, payment_settings)

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
        price_line = price_line.format(
            price_label=price_label,
            access_days=access_days,
            access_days_label=format_access_days_label(access_days),
        )

    trigger_line = ""
    if trigger == OFFER_TRIGGER_LIMIT_REACHED:
        trigger_line = str(payment_settings.get("offer_limit_reached_template") or "").strip()
    elif trigger == OFFER_TRIGGER_MODE_LOCKED:
        trigger_line = str(payment_settings.get("offer_locked_mode_template") or "").strip()
    elif trigger == OFFER_TRIGGER_PREVIEW_EXHAUSTED:
        trigger_line = str(
            payment_settings.get("offer_preview_exhausted_template")
            or payment_settings.get("offer_locked_mode_template")
            or ""
        ).strip()
    elif trigger == OFFER_TRIGGER_EMOTIONAL_ENGAGEMENT:
        trigger_line = str(
            payment_settings.get("offer_emotional_engagement_template")
            or payment_settings.get("offer_locked_mode_template")
            or ""
        ).strip()
    elif trigger == OFFER_TRIGGER_USEFUL_ADVICE:
        trigger_line = str(
            payment_settings.get("offer_useful_advice_template")
            or payment_settings.get("offer_locked_mode_template")
            or ""
        ).strip()

    if trigger_line:
        trigger_line = trigger_line.format(
            mode_name=mode_name or "Premium",
            access_days=access_days,
            access_days_label=format_access_days_label(access_days),
            premium_limit=premium_limit or 0,
            price_label=price_label,
        )
    teaser_line = _build_offer_teaser(trigger, mode_name)

    ordered_parts = (
        teaser_line,
        trigger_line,
        cta_text,
        price_line,
        benefits_text,
    ) if teaser_line else (
        trigger_line,
        cta_text,
        price_line,
        benefits_text,
    )
    return [part for part in ordered_parts if part]


def _build_buy_premium_callback_data(package_key: str, trigger: str) -> str:
    normalized_trigger = _normalize_offer_trigger(trigger)
    safe_package_key = str(package_key or "month").strip().lower() or "month"
    if normalized_trigger == OFFER_TRIGGER_DEFAULT:
        return f"{CALLBACK_BUY_PREMIUM}:{safe_package_key}"
    return f"{CALLBACK_BUY_PREMIUM}:{safe_package_key}:{normalized_trigger}"


def _build_confirm_virtual_payment_callback_data(package_key: str) -> str:
    safe_package_key = str(package_key or "month").strip().lower() or "month"
    return f"{CALLBACK_CONFIRM_VIRTUAL_PAYMENT}:{safe_package_key}"


def _parse_confirm_virtual_payment_callback_data(data: str | None, payment_service) -> str:
    raw = str(data or "").strip()
    prefix = f"{CALLBACK_CONFIRM_VIRTUAL_PAYMENT}:"
    if not raw.startswith(prefix):
        return payment_service.get_default_package_key()

    package_key = str(raw[len(prefix):]).strip().lower() or payment_service.get_default_package_key()
    if payment_service.get_package(package_key) is None:
        return payment_service.get_default_package_key()
    return package_key


def _parse_buy_premium_callback_data(data: str | None, payment_service) -> dict[str, str]:
    raw = str(data or "").strip()
    default_package_key = payment_service.get_default_package_key()
    if raw == CALLBACK_BUY_PREMIUM:
        return {"package_key": default_package_key, "trigger": OFFER_TRIGGER_DEFAULT}

    prefix = f"{CALLBACK_BUY_PREMIUM}:"
    if not raw.startswith(prefix):
        return {"package_key": default_package_key, "trigger": OFFER_TRIGGER_DEFAULT}

    parts = raw[len(prefix):].split(":")
    package_key = str(parts[0] or "").strip().lower() or default_package_key
    if payment_service.get_package(package_key) is None:
        package_key = default_package_key

    trigger = OFFER_TRIGGER_DEFAULT
    if len(parts) > 1:
        trigger = _normalize_offer_trigger(parts[1])
    return {"package_key": package_key, "trigger": trigger}


def _render_package_button_text(payment_settings: dict, package: dict) -> str:
    price_label = format_package_price_label(package, payment_settings)
    access_days = int(package.get("access_duration_days", 30))
    access_days_label = format_access_days_label(access_days)
    badge = str(package.get("badge") or "").strip()
    template = str(
        payment_settings.get("premium_menu_package_button_template")
        or payment_settings.get("premium_menu_buy_button_template")
        or "{title} • {price_label}"
    ).strip()

    try:
        rendered = template.format(
            title=package.get("title", "Premium"),
            badge=badge,
            price_label=price_label,
            access_days=access_days,
            access_days_label=access_days_label,
            description=package.get("description", ""),
        ).strip()
    except (KeyError, ValueError):
        rendered = ""

    if rendered:
        return rendered

    parts = [str(package.get("title") or "Premium").strip(), price_label]
    if badge:
        parts.append(badge)
    return " • ".join(part for part in parts if part)


def _build_premium_menu_keyboard(payment_service, payment_settings: dict, *, trigger: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=_render_package_button_text(payment_settings, package),
                callback_data=_build_buy_premium_callback_data(package["key"], trigger),
            )
        ]
        for package in payment_service.get_enabled_packages(payment_settings)
    ]
    back_text = str(payment_settings.get("premium_menu_back_button_text") or "← К режимам").strip() or "← К режимам"
    buttons.append([InlineKeyboardButton(text=back_text, callback_data=CALLBACK_PREMIUM_BACK_TO_MODES)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_invoice_recovery_keyboard(payment_settings: dict) -> InlineKeyboardMarkup:
    back_text = str(payment_settings.get("premium_menu_back_button_text") or "← К режимам").strip() or "← К режимам"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Попробовать другой тариф", callback_data=CALLBACK_OPEN_PREMIUM_MENU)],
            [InlineKeyboardButton(text=back_text, callback_data=CALLBACK_PREMIUM_BACK_TO_MODES)],
        ]
    )


def _build_virtual_payment_keyboard(payment_settings: dict, package: dict) -> InlineKeyboardMarkup:
    price_label = format_package_price_label(package, payment_settings)
    access_days = int(package.get("access_duration_days", 30))
    access_days_label = format_access_days_label(access_days)
    template = str(payment_settings.get("virtual_payment_button_template") or "").strip()
    try:
        confirm_text = template.format(
            package_key=package["key"],
            package_title=package["title"],
            price_label=price_label,
            access_days=access_days,
            access_days_label=access_days_label,
            description=package.get("description", ""),
        ).strip()
    except (KeyError, ValueError):
        confirm_text = ""
    confirm_text = confirm_text or f"Подтвердить тестовую оплату • {price_label}"
    back_text = str(payment_settings.get("premium_menu_back_button_text") or "← К режимам").strip() or "← К режимам"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=confirm_text,
                    callback_data=_build_confirm_virtual_payment_callback_data(package["key"]),
                )
            ],
            [InlineKeyboardButton(text=back_text, callback_data=CALLBACK_OPEN_PREMIUM_MENU)],
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


def _build_package_details(payment_service, payment_settings: dict) -> str:
    packages_title = str(payment_settings.get("premium_menu_packages_title") or "").strip()
    line_template = str(payment_settings.get("premium_menu_package_line_template") or "").strip()

    lines: list[str] = []
    if packages_title:
        lines.append(packages_title)

    for package in payment_service.get_enabled_packages(payment_settings):
        price_label = format_package_price_label(package, payment_settings)
        access_days = int(package.get("access_duration_days", 30))
        access_days_label = format_access_days_label(access_days)
        badge = str(package.get("badge") or "").strip()
        description = str(package.get("description") or "").strip()

        try:
            line = (line_template or "• {title} — {price_label} на {access_days_label}").format(
                title=package.get("title", "Premium"),
                badge=badge,
                price_label=price_label,
                access_days=access_days,
                access_days_label=access_days_label,
                description=description,
            ).strip()
        except (KeyError, ValueError):
            line = ""

        if not line:
            line = f"• {package.get('title', 'Premium')} — {price_label} на {access_days_label}"
        if description:
            line = f"{line}\n{description}"
        lines.append(line)

    return "\n".join(line for line in lines if line).strip()


def _build_premium_menu_details(
    payment_service,
    runtime_settings: dict | None,
    mode_catalog: dict | None,
    *,
    user_is_premium: bool,
) -> list[str]:
    if not isinstance(runtime_settings, dict):
        return []

    payment_settings = runtime_settings.get("payment", {})
    limits = runtime_settings.get("limits", {})
    primary_package = payment_service.get_default_package(payment_settings) or {}
    price_label = format_package_price_label(primary_package, payment_settings)
    access_days = max(1, int(primary_package.get("access_duration_days", 30)))
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

    package_details = _build_package_details(payment_service, payment_settings)
    if package_details:
        details.append(package_details)

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

    return [detail for detail in details if detail]


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

    primary_package = payment_service.get_default_package(payment_settings)
    text_parts = []
    if status_text:
        text_parts.append(status_text)
    text_parts.extend(
        _build_offer_intro(
            payment_settings,
            primary_package,
            user_id=message.from_user.id,
            trigger=trigger,
            mode_name=mode_name,
            premium_limit=premium_limit,
        )
    )
    text_parts.extend(
        _build_premium_menu_details(
            payment_service,
            runtime_settings,
            mode_catalog,
            user_is_premium=bool((user or {}).get("is_premium")),
        )
    )
    text = "\n\n".join(part for part in text_parts if part).strip() or str(payment_settings.get("product_description") or "").strip()
    reply_markup = _build_premium_menu_keyboard(payment_service, payment_settings, trigger=trigger)

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
            "default_package_key": (primary_package or {}).get("key"),
            "available_packages": [package["key"] for package in payment_service.get_enabled_packages(payment_settings)],
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
    package_key: str | None = None,
) -> bool:
    payment_settings = payment_service.get_payment_settings()
    package = payment_service.get_package(package_key, payment_settings)
    if not payment_service.is_enabled() or package is None:
        await message.answer(payment_settings["unavailable_message"])
        return False

    if payment_service.uses_virtual_payments(payment_settings):
        await message.answer(
            payment_service.build_virtual_checkout_text(package["key"]),
            reply_markup=_build_virtual_payment_keyboard(payment_settings, package),
        )
        await payment_service.track_invoice_opened(
            user_id=message.from_user.id,
            trigger=trigger,
            variant=payment_service.get_offer_variant(message.from_user.id),
            metadata={
                "mode_name": mode_name,
                "premium_limit": premium_limit,
                "package_key": package["key"],
                "package_title": package["title"],
                "payment_mode": "virtual",
            },
        )
        return True

    sent = await payment_service.send_premium_invoice(message, package["key"])
    if not sent:
        await message.answer(
            payment_settings["invoice_error_message"],
            reply_markup=_build_invoice_recovery_keyboard(payment_settings),
        )
        return False

    await payment_service.track_invoice_opened(
        user_id=message.from_user.id,
        trigger=trigger,
        variant=payment_service.get_offer_variant(message.from_user.id),
        metadata={
            "mode_name": mode_name,
            "premium_limit": premium_limit,
            "package_key": package["key"],
            "package_title": package["title"],
            "payment_mode": "telegram",
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

    parsed = _parse_buy_premium_callback_data(callback.data, payment_service)
    await send_premium_offer(
        callback.message,
        payment_service,
        user_service,
        trigger=parsed["trigger"],
        package_key=parsed["package_key"],
    )


@router.callback_query(F.data.startswith(CALLBACK_CONFIRM_VIRTUAL_PAYMENT))
async def confirm_virtual_payment_callback(callback: CallbackQuery, payment_service, user_service):
    await user_service.ensure_user(callback.from_user)
    await callback.answer()

    package_key = _parse_confirm_virtual_payment_callback_data(callback.data, payment_service)
    try:
        result = await payment_service.process_virtual_payment(
            user_id=callback.from_user.id,
            package_key=package_key,
        )
    except ValueError:
        logger.warning("Rejected virtual payment with invalid package for user %s", callback.from_user.id)
        return

    if callback.message is not None and hasattr(callback.message, "edit_text"):
        completed_text = str(
            payment_service.get_payment_settings().get("virtual_payment_completed_message")
            or "Тестовая оплата подтверждена."
        ).strip()
        try:
            await callback.message.edit_text(completed_text)
        except TelegramBadRequest:
            pass

    if callback.message is not None and hasattr(callback.message, "answer"):
        await callback.message.answer(payment_service.build_success_message(result))


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
    if result and result.get("referral") and result["referral"].get("reward_granted"):
        referral_settings = payment_service.referral_service.get_settings()
        referrer_id = result["referral"]["referrer_user_id"]
        try:
            await message.bot.send_message(referrer_id, referral_settings["referrer_reward_message"])
        except Exception:
            pass
