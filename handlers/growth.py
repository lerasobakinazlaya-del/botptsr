from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.growth_keyboard import build_referral_keyboard, build_telegram_share_url


router = Router(name="growth-router")

CALLBACK_OPEN_REFERRAL_MENU = "open_referral_menu"
CALLBACK_SHARE_INSIGHT = "share_insight"
CALLBACK_REFERRAL_INFO = "referral_info"


def build_ref_link(*, username: str, prefix: str, user_id: int) -> str:
    return f"https://t.me/{username}?start={prefix}{user_id}"


def build_referral_message(referral_settings: dict, *, ref_link: str) -> str:
    reward_days = int(referral_settings.get("reward_premium_days", 0) or 0)
    reward_plan_key = str(referral_settings.get("reward_plan_key") or "pro").strip().lower() or "pro"
    share_text = str(referral_settings.get("share_text_template") or "").replace("{ref_link}", ref_link).strip()
    reward_label = "Premium" if reward_plan_key == "premium" else "Pro"

    parts = [
        str(referral_settings.get("program_title") or "").strip(),
        str(referral_settings.get("program_description") or "").strip(),
        f"Бонус: тебе и другу по {reward_days} дней {reward_label} после первой успешной оплаты друга." if reward_days > 0 else "",
        share_text,
    ]
    return "\n\n".join(part for part in parts if part)


def build_shareable_insight_text(*, share_card: dict, ref_link: str | None = None) -> str:
    title = str(share_card.get("title") or "Инсайт дня").strip()
    summary = str(share_card.get("summary") or "").strip()
    action = str(share_card.get("action") or "").strip()

    parts = [title]
    if summary:
        parts.append(summary)
    if action:
        parts.append(f"Что можно сделать: {action}")
    if ref_link:
        parts.append(f"Попробовать бота: {ref_link}")
    return "\n\n".join(parts)


@router.callback_query(F.data == CALLBACK_OPEN_REFERRAL_MENU)
async def open_referral_menu_callback(callback: CallbackQuery, admin_settings_service, monetization_repository):
    if callback.message is None:
        await callback.answer()
        return

    runtime = admin_settings_service.get_runtime_settings()
    referral_settings = runtime["referral"]
    me = await callback.bot.get_me()
    ref_link = build_ref_link(
        username=me.username,
        prefix=referral_settings["start_parameter_prefix"],
        user_id=callback.from_user.id,
    )
    message_text = build_referral_message(referral_settings, ref_link=ref_link)
    share_url = build_telegram_share_url(
        str(referral_settings.get("share_text_template") or "").replace("{ref_link}", ref_link)
    )
    keyboard = build_referral_keyboard(
        share_url=share_url,
        share_button_text="Поделиться ссылкой",
        info_callback=CALLBACK_REFERRAL_INFO,
    )
    await callback.message.answer(message_text, reply_markup=keyboard)
    await monetization_repository.log_event(
        user_id=callback.from_user.id,
        event_name="referral_menu_opened",
        metadata={
            "source": "inline_menu",
            "ref_link": ref_link,
        },
    )
    await callback.answer()


@router.callback_query(F.data == CALLBACK_REFERRAL_INFO)
async def referral_info_callback(callback: CallbackQuery, admin_settings_service):
    runtime = admin_settings_service.get_runtime_settings()
    referral_settings = runtime["referral"]
    reward_days = int(referral_settings.get("reward_premium_days", 0) or 0)
    reward_plan_key = str(referral_settings.get("reward_plan_key") or "pro").strip().lower() or "pro"
    reward_label = "Premium" if reward_plan_key == "premium" else "Pro"
    await callback.answer(
        f"Друг приходит по ссылке, общается с ботом и после первой успешной оплаты вы оба получаете {reward_days} дней {reward_label}.",
        show_alert=True,
    )


@router.callback_query(F.data == CALLBACK_SHARE_INSIGHT)
async def share_insight_callback(callback: CallbackQuery, state_repository, admin_settings_service, monetization_repository):
    if callback.message is None:
        await callback.answer()
        return

    state = await state_repository.get(callback.from_user.id)
    share_card = dict((state or {}).get("growth_share_card") or {})
    if not share_card:
        await callback.answer("Сначала получи полезный ответ, и я подготовлю карточку для шаринга.", show_alert=True)
        return

    runtime = admin_settings_service.get_runtime_settings()
    referral_settings = runtime["referral"]
    me = await callback.bot.get_me()
    ref_link = build_ref_link(
        username=me.username,
        prefix=referral_settings["start_parameter_prefix"],
        user_id=callback.from_user.id,
    )
    share_text = build_shareable_insight_text(share_card=share_card, ref_link=ref_link)
    share_url = build_telegram_share_url(share_text)
    keyboard = build_referral_keyboard(
        share_url=share_url,
        share_button_text="Поделиться в Telegram",
        info_callback=CALLBACK_OPEN_REFERRAL_MENU,
    )
    await callback.message.answer("Готово. Ниже — быстрый шаринг инсайта:", reply_markup=keyboard)
    await callback.message.answer(share_text)
    await monetization_repository.log_event(
        user_id=callback.from_user.id,
        event_name="insight_shared",
        metadata={
            "title": share_card.get("title") or "",
            "has_action": bool(share_card.get("action")),
        },
    )
    await callback.answer()
