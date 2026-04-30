import logging
from datetime import datetime, timezone
from math import ceil
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from handlers.growth import CALLBACK_OPEN_REFERRAL_MENU, CALLBACK_REFERRAL_INFO, CALLBACK_SHARE_INSIGHT
from keyboards.growth_keyboard import build_growth_reply_keyboard, build_referral_keyboard, build_telegram_share_url
from handlers.modes import show_modes_menu
from handlers.payments import (
    OFFER_TRIGGER_EMOTIONAL_ENGAGEMENT,
    OFFER_TRIGGER_LIMIT_REACHED,
    OFFER_TRIGGER_MODE_LOCKED,
    OFFER_TRIGGER_PREVIEW_EXHAUSTED,
    OFFER_TRIGGER_USEFUL_ADVICE,
    show_premium_menu,
)
from services.ai_profile_service import resolve_ai_profile
from services.ai_service import AIBackpressureError
from services.telegram_formatting import (
    TelegramFormattingOptions,
    escape_plain_text_for_telegram,
    format_model_response_for_telegram,
)


router = Router()
logger = logging.getLogger(__name__)


def _truncate_sentence(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    truncated = normalized[: max(0, limit - 1)].rstrip(" ,.;:-")
    return f"{truncated}…"


def _build_share_card(response: str) -> dict[str, str] | None:
    normalized = " ".join(str(response or "").split()).strip()
    if len(normalized) < 90:
        return None

    segments = [segment.strip(" -•") for segment in normalized.replace("•", ". ").split(".") if segment.strip()]
    summary = _truncate_sentence(segments[0] if segments else normalized, 180)
    action = _truncate_sentence(segments[1] if len(segments) > 1 else "", 120)
    title = "Инсайт, который мне дал AI-компаньон"
    return {
        "title": title,
        "summary": summary,
        "action": action,
    }


def _is_sensitive_growth_context(user_text: str, response: str) -> bool:
    text = f"{user_text} {response}".lower()
    sensitive_keywords = (
        "секс",
        "сексу",
        "группов",
        "фантаз",
        "возбужд",
        "тело",
        "тел",
        "ревност",
        "интим",
        "эрот",
        "порно",
        "стыд",
        "птср",
        "паник",
        "самоповреж",
        "суицид",
    )
    return any(keyword in text for keyword in sensitive_keywords)


def _is_actionable_share_context(response: str) -> bool:
    text = str(response or "").lower()
    actionable_keywords = (
        "шаг",
        "план",
        "сделай",
        "выбери",
        "попробуй",
        "можно сделать",
        "сначала",
        "затем",
        "сегодня",
        "важно",
    )
    return any(keyword in text for keyword in actionable_keywords)


def _should_offer_growth_actions(
    *,
    state: dict | None,
    user_text: str,
    response: str,
    share_card: dict[str, str] | None,
) -> bool:
    if not share_card:
        return False
    if _is_sensitive_growth_context(user_text, response):
        return False
    if int((state or {}).get("interaction_count", 0) or 0) < 5:
        return False
    return _is_actionable_share_context(response)


def _normalize_onboarding_prompts(ui_settings: dict) -> set[str]:
    return {
        str(item).strip().lower()
        for item in (ui_settings.get("onboarding_prompt_buttons") or [])
        if str(item).strip()
    }


async def _send_referral_menu(
    message: Message,
    referral_settings: dict,
    user_id: int,
    monetization_repository=None,
) -> None:
    me = await message.bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={referral_settings['start_parameter_prefix']}{user_id}"
    reward_days = int(referral_settings.get("reward_premium_days", 0) or 0)
    reward_plan_key = str(referral_settings.get("reward_plan_key") or "pro").strip().lower() or "pro"
    reward_label = "Premium" if reward_plan_key == "premium" else "Pro"
    share_text = str(referral_settings["share_text_template"]).replace("{ref_link}", ref_link)
    share_url = build_telegram_share_url(share_text)
    text = "\n\n".join(
        part
        for part in (
            str(referral_settings.get("program_title") or "").strip(),
            str(referral_settings.get("program_description") or "").strip(),
            (
                f"Бонус: тебе и другу по {reward_days} дней {reward_label} "
                "после первой успешной оплаты друга."
                if reward_days > 0
                else ""
            ),
            share_text,
        )
        if part
    )
    await message.answer(
        text,
        reply_markup=build_referral_keyboard(
            share_url=share_url,
            share_button_text="Поделиться ссылкой",
            info_callback=CALLBACK_REFERRAL_INFO,
        ),
    )
    if monetization_repository is not None:
        await monetization_repository.log_event(
            user_id=user_id,
            event_name="referral_menu_opened",
            metadata={
                "source": "chat_command",
                "ref_link": ref_link,
            },
        )


def _proactive_help_text() -> str:
    return (
        "Команды инициативности:\n"
        "/proactive - показать статус\n"
        "/proactive on - бот может иногда писать первым\n"
        "/proactive off - отключить инициативные сообщения\n"
        "/quiet - быстрый тихий режим\n"
        "/quiet off - вернуть инициативные сообщения"
    )


def _set_proactive_enabled(state: dict, enabled: bool) -> dict:
    updated = dict(state or {})
    proactive_preferences = dict(updated.get("proactive_preferences") or {})
    proactive_preferences["enabled"] = bool(enabled)
    proactive_preferences["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated["proactive_preferences"] = proactive_preferences
    return updated


def _set_user_timezone(state: dict, timezone_name: str | None) -> dict:
    updated = dict(state or {})
    proactive_preferences = dict(updated.get("proactive_preferences") or {})
    proactive_preferences["timezone"] = timezone_name
    proactive_preferences["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated["proactive_preferences"] = proactive_preferences
    return updated


def _today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _subscription_plan(user: dict[str, object] | None) -> str:
    normalized = str((user or {}).get("subscription_plan") or "").strip().lower()
    if normalized in {"free", "pro", "premium"}:
        return normalized
    return "premium" if bool((user or {}).get("is_premium")) else "free"


def _plan_daily_limit(plan_key: str, limits_settings: dict) -> tuple[bool, int, str, str, list[int]]:
    if plan_key == "premium":
        return (
            bool(limits_settings.get("premium_daily_messages_enabled")),
            max(1, int(limits_settings.get("premium_daily_messages_limit", 200))),
            str(limits_settings.get("premium_daily_limit_message") or "").strip(),
            str(limits_settings.get("premium_daily_warning_template") or "").strip(),
            _normalize_int_list(limits_settings.get("premium_daily_warning_thresholds")),
        )
    if plan_key == "pro":
        return (
            bool(limits_settings.get("pro_daily_messages_enabled", True)),
            max(1, int(limits_settings.get("pro_daily_messages_limit", 80))),
            str(limits_settings.get("pro_daily_limit_message") or "").strip(),
            str(limits_settings.get("pro_daily_warning_template") or "").strip(),
            _normalize_int_list(limits_settings.get("pro_daily_warning_thresholds")),
        )
    return (
        bool(limits_settings.get("free_daily_messages_enabled")),
        max(1, int(limits_settings.get("free_daily_messages_limit", 12))),
        str(limits_settings.get("free_daily_limit_message") or "").strip(),
        str(limits_settings.get("free_daily_warning_template") or "").strip(),
        _normalize_int_list(limits_settings.get("free_daily_warning_thresholds")),
    )


def _normalize_int_list(raw: object) -> list[int]:
    if isinstance(raw, str):
        items = raw.replace(",", "\n").splitlines()
    else:
        items = list(raw or [])

    normalized: list[int] = []
    for item in items:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized


def _remember_notice(state: dict | None, bucket: str, marker: str | int) -> tuple[dict, bool]:
    updated = dict(state or {})
    notifications = dict(updated.get("monetization_notifications") or {})
    day_key = _today_key()
    day_notifications = dict(notifications.get(day_key) or {})
    sent_markers = {str(item) for item in day_notifications.get(bucket, [])}
    marker_key = str(marker)
    if marker_key in sent_markers:
        return updated, False

    sent_markers.add(marker_key)
    day_notifications[bucket] = sorted(sent_markers)
    notifications[day_key] = day_notifications
    updated["monetization_notifications"] = {
        key: notifications[key]
        for key in sorted(notifications.keys(), reverse=True)[:7]
    }
    return updated, True


def _build_quota_notice(
    state: dict | None,
    user: dict[str, object],
    today_count: int,
    limits_settings: dict,
) -> tuple[dict, str | None]:
    plan_key = _subscription_plan(user)
    enabled, limit, limit_message, warning_template, thresholds_raw = _plan_daily_limit(plan_key, limits_settings)
    if not enabled:
        return dict(state or {}), None
    remaining = max(0, limit - today_count)
    thresholds = set(thresholds_raw)
    if remaining not in thresholds:
        return dict(state or {}), None
    updated_state, should_send = _remember_notice(state, f"{plan_key}_daily", remaining)
    if not should_send:
        return updated_state, None
    if remaining == 0:
        return updated_state, limit_message or None
    if not warning_template:
        return updated_state, None
    return updated_state, warning_template.format(remaining=remaining, limit=limit)


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def _is_sensitive_monetization_context(*, user_text: str, state: dict | None = None) -> bool:
    text = str(user_text or "").lower()
    emotional_tone = str((state or {}).get("emotional_tone") or "").strip().lower()
    if emotional_tone in {"overwhelmed", "anxious", "guarded", "crisis"}:
        return True

    sensitive_keywords = (
        "суицид",
        "самоуб",
        "самоповреж",
        "умер",
        "умерла",
        "смерт",
        "похорон",
        "паник",
        "птср",
        "травм",
        "врач",
        "скорая",
        "сердц",
        "аритм",
        "боль в груди",
        "одыш",
        "обмор",
        "насили",
    )
    return any(keyword in text for keyword in sensitive_keywords)


def _should_trigger_emotional_paywall(
    *,
    user: dict[str, object] | None,
    state: dict | None,
    user_text: str,
    response: str,
) -> bool:
    if _subscription_plan(user) != "free":
        return False
    if _is_sensitive_monetization_context(user_text=user_text, state=state):
        return False
    if len(str(response or "").strip()) < 140:
        return False
    if int((state or {}).get("interaction_count", 0) or 0) < 3:
        return False
    emotional_keywords = (
        "тревог",
        "тяжело",
        "страш",
        "одино",
        "отношен",
        "выгор",
        "перегруз",
        "больно",
    )
    return _contains_any_keyword(user_text, emotional_keywords)


def _should_trigger_useful_advice_paywall(
    *,
    user: dict[str, object] | None,
    active_mode: str,
    user_text: str,
    response: str,
) -> bool:
    if _subscription_plan(user) != "free":
        return False
    if _is_sensitive_monetization_context(user_text=user_text):
        return False
    request_keywords = (
        "помоги",
        "разбери",
        "разобрать",
        "что делать",
        "как лучше",
        "план",
        "шаг",
    )
    response_keywords = ("1.", "2.", "•", "шаг", "план")
    return (
        active_mode in {"mentor", "dominant", "base"}
        and _contains_any_keyword(user_text, request_keywords)
        and _contains_any_keyword(response, response_keywords)
    )


def _build_subscription_expiry_notice(
    state: dict | None,
    user: dict[str, object],
    payment_service,
) -> tuple[dict, str | None]:
    if not user.get("is_premium"):
        return dict(state or {}), None

    premium_expires_at = str(user.get("premium_expires_at") or "").strip()
    if not premium_expires_at:
        return dict(state or {}), None

    try:
        expires_at = datetime.strptime(premium_expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return dict(state or {}), None

    seconds_left = (expires_at - datetime.now(timezone.utc)).total_seconds()
    if seconds_left <= 0:
        return dict(state or {}), None

    days_left = max(1, ceil(seconds_left / 86400))
    payment_settings = payment_service.get_payment_settings()
    reminder_days = set(_normalize_int_list(payment_settings.get("renewal_reminder_days")))
    if days_left not in reminder_days:
        return dict(state or {}), None

    updated_state, should_send = _remember_notice(state, "premium_expiry", days_left)
    if not should_send:
        return updated_state, None

    template = str(payment_settings.get("expiry_reminder_template") or "").strip()
    if not template:
        return updated_state, None
    return updated_state, template.format(
        days=days_left,
        expires_at=payment_service.format_expiry_text(premium_expires_at),
    )


async def _handle_timezone_command(message: Message, user_preference_repository, state_repository) -> bool:
    raw_text = (message.text or "").strip()
    command, _, argument = raw_text.partition(" ")
    if command.lower() != "/timezone":
        return False

    state = await state_repository.get(message.from_user.id)
    proactive_preferences = await user_preference_repository.get_preferences(
        message.from_user.id,
        fallback=state.get("proactive_preferences"),
    )
    current_timezone = str(proactive_preferences.get("timezone") or "").strip()
    normalized_argument = argument.strip()

    if not normalized_argument:
        await message.answer(
            "Текущая timezone: "
            + (current_timezone or "не задана, используется общая timezone бота.")
            + "\n\nПример: /timezone Europe/Moscow"
        )
        return True

    if normalized_argument.lower() in {"off", "reset", "default"}:
        new_state = _set_user_timezone(state, None)
        await state_repository.save(message.from_user.id, new_state)
        await user_preference_repository.set_timezone(message.from_user.id, None)
        await message.answer("Личная timezone сброшена. Теперь используется общая timezone бота.")
        return True

    try:
        ZoneInfo(normalized_argument)
    except Exception:
        await message.answer(
            "Не смог распознать timezone.\n\n"
            "Используй формат вроде Europe/Moscow, Europe/Berlin или America/New_York."
        )
        return True

    new_state = _set_user_timezone(state, normalized_argument)
    await state_repository.save(message.from_user.id, new_state)
    await user_preference_repository.set_timezone(message.from_user.id, normalized_argument)
    await message.answer(f"Timezone сохранена: {normalized_argument}")
    return True


async def _handle_proactive_command(message: Message, user_preference_repository, state_repository) -> bool:
    raw_text = (message.text or "").strip()
    command, _, argument = raw_text.partition(" ")
    command = command.lower()
    argument = argument.strip().lower()

    if command not in {"/proactive", "/quiet"}:
        return False

    state = await state_repository.get(message.from_user.id)
    proactive_preferences = await user_preference_repository.get_preferences(
        message.from_user.id,
        fallback=state.get("proactive_preferences"),
    )
    is_enabled = bool(proactive_preferences.get("proactive_enabled", True))

    if command == "/quiet":
        if argument in {"", "on"}:
            new_state = _set_proactive_enabled(state, False)
            await state_repository.save(message.from_user.id, new_state)
            await user_preference_repository.set_proactive_enabled(message.from_user.id, False)
            await message.answer(
                "Тихий режим включён. Я не буду писать первой, пока ты сам снова это не разрешишь.\n\n"
                "Вернуть можно командой /proactive on или /quiet off."
            )
            return True
        if argument == "off":
            new_state = _set_proactive_enabled(state, True)
            await state_repository.save(message.from_user.id, new_state)
            await user_preference_repository.set_proactive_enabled(message.from_user.id, True)
            await message.answer("Тихий режим выключен. Если диалог подходящий, я снова смогу иногда написать первой.")
            return True
        await message.answer(_proactive_help_text())
        return True

    if argument in {"", "status"}:
        await message.answer(
            "Статус инициативных сообщений: "
            + ("включены." if is_enabled else "выключены.")
            + "\n\n"
            + _proactive_help_text()
        )
        return True
    if argument == "on":
        new_state = _set_proactive_enabled(state, True)
        await state_repository.save(message.from_user.id, new_state)
        await user_preference_repository.set_proactive_enabled(message.from_user.id, True)
        await message.answer("Инициативные сообщения включены. Я смогу иногда аккуратно напомнить о себе.")
        return True
    if argument == "off":
        new_state = _set_proactive_enabled(state, False)
        await state_repository.save(message.from_user.id, new_state)
        await user_preference_repository.set_proactive_enabled(message.from_user.id, False)
        await message.answer("Инициативные сообщения отключены. Буду писать только когда ты сам напишешь.")
        return True

    await message.answer(_proactive_help_text())
    return True


@router.message()
async def chat_handler(
    message: Message,
    message_repository,
    ai_service,
    long_term_memory_service,
    state_repository,
    user_preference_repository,
    payment_service,
    user_service,
    referral_service,
    admin_settings_service,
    monetization_repository,
    conversation_summary_service,
    chat_session_service,
    mode_access_service,
    db,
):
    runtime_settings = admin_settings_service.get_runtime_settings()
    ai_settings = runtime_settings["ai"]
    chat_settings = runtime_settings["chat"]
    ui_settings = runtime_settings["ui"]
    limits_settings = runtime_settings["limits"]
    referral_settings = runtime_settings["referral"]
    mode_catalog = admin_settings_service.get_mode_catalog()

    if not message.text:
        await message.answer(chat_settings["non_text_message"])
        return

    user_id = message.from_user.id
    user_text = message.text.strip()
    onboarding_prompt_texts = _normalize_onboarding_prompts(ui_settings)
    user = await user_service.get_user(user_id)
    if user is None and message.from_user is not None:
        await user_service.ensure_user(message.from_user)
        user = await user_service.get_user(user_id)

    if user_text == ui_settings["write_button_text"]:
        await message.answer(chat_settings["write_prompt_message"])
        return

    if await _handle_proactive_command(message, user_preference_repository, state_repository):
        return
    if await _handle_timezone_command(message, user_preference_repository, state_repository):
        return

    if user_text == ui_settings["modes_button_text"]:
        await show_modes_menu(message, user_service, admin_settings_service)
        return

    if user_text == ui_settings["premium_button_text"]:
        await show_premium_menu(message, payment_service, user_service, admin_settings_service)
        return

    if user_text.lower() in {"/ref", "рефералка", "реферальная ссылка"} and referral_settings["enabled"]:
        await _send_referral_menu(message, referral_settings, user_id, monetization_repository)
        return

    async with chat_session_service.user_session(user_id):
        limits_bypass_for_admins = limits_settings.get("admins_bypass_daily_limits", True)
        should_apply_limits = user is not None and (
            not user.get("is_admin") or not limits_bypass_for_admins
        )
        today_count = 0

        if should_apply_limits:
            today_count = await message_repository.get_user_messages_count_today(user_id)
            plan_key = _subscription_plan(user)
            limit_enabled, limit_value, limit_message, _, _ = _plan_daily_limit(plan_key, limits_settings)
            if limit_enabled and today_count >= limit_value:
                await message.answer(limit_message)
                if plan_key != "premium":
                    await show_premium_menu(
                        message,
                        payment_service,
                        user_service,
                        admin_settings_service,
                        trigger=OFFER_TRIGGER_LIMIT_REACHED,
                        premium_limit=int(limits_settings.get("premium_daily_messages_limit", 200)),
                    )
                return

        state = await state_repository.get(user_id)
        logger.debug("[STATE] Loaded for user %s", user_id)
        active_mode = str(state.get("active_mode") or (user or {}).get("active_mode") or "base")
        ai_profile = resolve_ai_profile(ai_settings, active_mode, _subscription_plan(user))
        selection_status = mode_access_service.get_selection_status(
            user=user or {},
            mode_key=active_mode,
            state=state,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )

        if not selection_status["allowed"]:
            mode_meta = mode_catalog.get(active_mode, {})
            mode_name = str(mode_meta.get("name") or active_mode)
            await message.answer(
                limits_settings["mode_preview_exhausted_message"].format(
                    mode_name=mode_name,
                    daily_limit=selection_status["daily_limit"],
                )
            )
            await show_premium_menu(
                message,
                payment_service,
                user_service,
                admin_settings_service,
                trigger=OFFER_TRIGGER_PREVIEW_EXHAUSTED,
                mode_name=mode_name,
                premium_limit=int(limits_settings.get("premium_daily_messages_limit", 200)),
            )
            return

        history = await message_repository.get_last_messages(
            user_id=user_id,
            limit=ai_profile["history_message_limit"],
        )

        if chat_settings["typing_action_enabled"]:
            await message.bot.send_chat_action(user_id, "typing")

        async def remember_user_message() -> None:
            try:
                await long_term_memory_service.capture_from_message(user_id, user_text)
            except Exception:
                logger.exception("LONG TERM MEMORY ERROR")

        try:
            result = await ai_service.generate_response(
                user_id=user_id,
                history=history,
                user_message=user_text,
                state=state,
                subscription_plan=_subscription_plan(user),
            )
        except AIBackpressureError:
            await message_repository.save(user_id, "user", user_text)
            await remember_user_message()
            await message.answer(chat_settings["busy_message"])
            return
        except Exception:
            logger.exception("AI ERROR")
            await message_repository.save(user_id, "user", user_text)
            await remember_user_message()
            await message.answer(chat_settings["ai_error_message"])
            return

        response = result.response
        new_state = result.new_state
        share_card = _build_share_card(response)
        if _is_sensitive_growth_context(user_text, response):
            share_card = None

        if new_state is None:
            logger.warning(
                "[STATE] AI returned None for user %s, keeping previous state",
                user_id,
            )
            new_state = state
        if share_card:
            new_state = dict(new_state or {})
            new_state["growth_share_card"] = share_card
        onboarding_state = dict((new_state or {}).get("onboarding") or {})
        acquisition_state = dict((new_state or {}).get("acquisition") or {})
        growth_events: list[tuple[str, dict[str, object]]] = []
        if not str(onboarding_state.get("completed_at") or "").strip():
            onboarding_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            if user_text.strip().lower() in onboarding_prompt_texts:
                onboarding_state["starter_prompt"] = user_text.strip()
            growth_events.append(
                (
                    "onboarding_completed",
                    {
                        "source": acquisition_state.get("source") or "direct",
                        "campaign": acquisition_state.get("campaign") or "",
                        "starter_prompt": onboarding_state.get("starter_prompt") or "",
                    },
                )
            )
        new_state["onboarding"] = onboarding_state

        response_mode = str(new_state.get("adaptive_mode") or new_state.get("active_mode") or active_mode)
        mode_config = admin_settings_service.get_modes().get(response_mode, {})
        formatting_options = TelegramFormattingOptions(
            allow_bold=bool(mode_config.get("allow_bold", False)),
            allow_italic=bool(mode_config.get("allow_italic", False)),
        )
        formatted_response = format_model_response_for_telegram(response, formatting_options)
        post_response_notices: list[str] = []
        soft_paywall_trigger: str | None = None
        should_offer_growth_actions = False

        try:
            new_state = mode_access_service.register_successful_message(
                new_state,
                mode_key=active_mode,
                user=user or {},
                runtime_settings=runtime_settings,
                mode_catalog=mode_catalog,
            )
            if should_apply_limits:
                new_state, quota_notice = _build_quota_notice(
                    new_state,
                    user or {},
                    today_count + 1,
                    limits_settings,
                )
                if quota_notice:
                    post_response_notices.append(quota_notice)
            new_state, expiry_notice = _build_subscription_expiry_notice(
                new_state,
                user or {},
                payment_service,
            )
            if expiry_notice:
                post_response_notices.append(expiry_notice)
            if _should_trigger_emotional_paywall(
                user=user or {},
                state=new_state,
                user_text=user_text,
                response=response,
            ):
                new_state, should_send = _remember_notice(new_state, "soft_paywall", "emotional")
                if should_send:
                    soft_paywall_trigger = OFFER_TRIGGER_EMOTIONAL_ENGAGEMENT
            elif _should_trigger_useful_advice_paywall(
                user=user or {},
                active_mode=active_mode,
                user_text=user_text,
                response=response,
            ):
                new_state, should_send = _remember_notice(new_state, "soft_paywall", "useful")
                if should_send:
                    soft_paywall_trigger = OFFER_TRIGGER_USEFUL_ADVICE
            if referral_settings["enabled"] and _should_offer_growth_actions(
                state=new_state,
                user_text=user_text,
                response=response,
                share_card=share_card,
            ):
                new_state, should_offer_growth_actions = _remember_notice(
                    new_state,
                    "growth_actions",
                    "share",
                )
            async with db.transaction():
                await message_repository.save(user_id, "user", user_text, commit=False)
                await state_repository.save(user_id, new_state, commit=False)
                await message_repository.save(user_id, "assistant", response, commit=False)
        except Exception:
            logger.exception("DB ERROR while saving chat exchange")
            await message.answer(chat_settings["ai_error_message"])
            return

        await remember_user_message()

        for event_name, metadata in growth_events:
            await monetization_repository.log_event(
                user_id=user_id,
                event_name=event_name,
                metadata=metadata,
            )

        activation_threshold = max(1, int(referral_settings.get("activation_user_messages_threshold", 10) or 10))
        message_stats = await message_repository.get_user_message_stats(user_id)
        if (
            int(message_stats.get("user_messages", 0) or 0) >= activation_threshold
            and not str((new_state.get("onboarding") or {}).get("activation_reached_at") or "").strip()
        ):
            onboarding_state = dict(new_state.get("onboarding") or {})
            onboarding_state["activation_reached_at"] = datetime.now(timezone.utc).isoformat()
            new_state["onboarding"] = onboarding_state
            await state_repository.save(user_id, new_state)
            await monetization_repository.log_event(
                user_id=user_id,
                event_name="activation_reached",
                metadata={
                    "source": acquisition_state.get("source") or "direct",
                    "campaign": acquisition_state.get("campaign") or "",
                    "user_messages": int(message_stats.get("user_messages", 0) or 0),
                },
            )
            referral_reward = await referral_service.process_activation(user_id)
            if referral_reward and referral_reward.get("reward_granted"):
                try:
                    await message.bot.send_message(
                        referral_reward["referrer_user_id"],
                        referral_settings["referrer_reward_message"],
                    )
                except Exception:
                    logger.exception("REFERRAL REWARD NOTIFY ERROR")

        try:
            conversation_summary_service.schedule_refresh(user_id, new_state)
        except Exception:
            logger.exception("SUMMARY SCHEDULER ERROR")

        reply_markup = (
            build_growth_reply_keyboard(
                share_callback=CALLBACK_SHARE_INSIGHT,
                referral_callback=CALLBACK_OPEN_REFERRAL_MENU,
            )
            if should_offer_growth_actions
            else None
        )
        try:
            await message.answer(
                formatted_response or escape_plain_text_for_telegram(response),
                reply_markup=reply_markup,
            )
        except TelegramBadRequest:
            logger.exception("TELEGRAM FORMAT ERROR")
            await message.answer(
                escape_plain_text_for_telegram(response),
                reply_markup=reply_markup,
            )
        if soft_paywall_trigger:
            await show_premium_menu(
                message,
                payment_service,
                user_service,
                admin_settings_service,
                trigger=soft_paywall_trigger,
                premium_limit=int(limits_settings.get("premium_daily_messages_limit", 200)),
            )
        for notice in post_response_notices:
            await message.answer(notice)
