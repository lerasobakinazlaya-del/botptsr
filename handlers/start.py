from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from datetime import datetime, timezone

from aiogram.types import FSInputFile, KeyboardButton, Message, ReplyKeyboardMarkup


router = Router()
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_main_keyboard(ui_settings: dict) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ui_settings["write_button_text"])],
            [KeyboardButton(text=ui_settings["modes_button_text"])],
            [KeyboardButton(text=ui_settings["premium_button_text"])],
        ],
        resize_keyboard=True,
        input_field_placeholder=ui_settings["input_placeholder"],
    )


def get_onboarding_keyboard(ui_settings: dict) -> ReplyKeyboardMarkup | None:
    prompts = [
        str(item).strip()
        for item in (ui_settings.get("onboarding_prompt_buttons") or [])
        if str(item).strip()
    ]
    if not prompts:
        return None

    rows = [[KeyboardButton(text=prompt)] for prompt in prompts[:4]]
    premium_text = str(ui_settings.get("premium_button_text") or "").strip()
    if premium_text and premium_text not in prompts[:4]:
        rows.append([KeyboardButton(text=premium_text)])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=str(ui_settings.get("onboarding_input_placeholder") or ui_settings["input_placeholder"]).strip(),
    )


def _extract_start_parameter(text: str) -> str:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _parse_start_context(text: str, prefix: str) -> dict[str, object]:
    parameter = _extract_start_parameter(text)
    context: dict[str, object] = {
        "raw_parameter": parameter,
        "referrer_user_id": None,
        "source": "",
        "campaign": "",
    }
    if not parameter:
        return context

    parts = [part.strip() for part in parameter.split("__") if part.strip()]
    aliases = {
        "tt": "tiktok",
        "tiktok": "tiktok",
        "tg": "telegram",
        "telegram": "telegram",
        "rd": "reddit",
        "reddit": "reddit",
        "ig": "instagram",
        "reels": "instagram_reels",
    }
    for part in parts:
        if part.startswith(prefix):
            raw_id = part[len(prefix):].strip()
            context["referrer_user_id"] = int(raw_id) if raw_id.isdigit() else None
            continue
        if part.startswith("src_"):
            context["source"] = part[4:].strip().lower()
            continue
        if part.startswith("cmp_"):
            context["campaign"] = part[4:].strip().lower()
            continue
        normalized = aliases.get(part.strip().lower())
        if normalized and not context["source"]:
            context["source"] = normalized

    if context["referrer_user_id"] and not context["source"]:
        context["source"] = "referral"
    return context


def _build_welcome_followup_text(ui_settings: dict) -> str:
    return str(ui_settings.get("welcome_followup_text") or "").strip()


@router.message(CommandStart())
async def start_handler(
    message: Message,
    user_service,
    admin_settings_service,
    referral_service,
    state_repository=None,
    monetization_repository=None,
):
    is_new_user = await user_service.ensure_user(message.from_user)
    runtime = admin_settings_service.get_runtime_settings()
    ui_settings = runtime["ui"]
    referral_settings = runtime["referral"]
    keyboard = get_main_keyboard(ui_settings)
    onboarding_keyboard = get_onboarding_keyboard(ui_settings)
    avatar_path = str(ui_settings.get("start_avatar_path") or "").strip()
    avatar_file = PROJECT_ROOT / avatar_path if avatar_path else None
    start_context = _parse_start_context(
        message.text or "",
        referral_settings["start_parameter_prefix"],
    )

    async def send_welcome(text: str) -> None:
        if avatar_file and avatar_file.exists():
            await message.answer_photo(
                photo=FSInputFile(avatar_file),
                caption=text,
                reply_markup=keyboard,
            )
            return
        await message.answer(text, reply_markup=keyboard)

    async def send_user_welcome() -> None:
        await send_welcome(ui_settings["welcome_user_text"])
        if not is_new_user:
            return
        followup_text = _build_welcome_followup_text(ui_settings)
        if followup_text:
            await message.answer(followup_text, reply_markup=onboarding_keyboard)

    if is_new_user and state_repository is not None:
        state = await state_repository.get(message.from_user.id)
        onboarding = dict(state.get("onboarding") or {})
        acquisition = dict(state.get("acquisition") or {})
        started_at = datetime.now(timezone.utc).isoformat()
        onboarding["started_at"] = onboarding.get("started_at") or started_at
        acquisition["source"] = str(start_context.get("source") or "").strip() or None
        acquisition["campaign"] = str(start_context.get("campaign") or "").strip() or None
        acquisition["referrer_user_id"] = start_context.get("referrer_user_id")
        acquisition["start_parameter"] = str(start_context.get("raw_parameter") or "").strip() or None
        state["onboarding"] = onboarding
        state["acquisition"] = acquisition
        await state_repository.save(message.from_user.id, state)

    if is_new_user and monetization_repository is not None:
        metadata = {
            "source": str(start_context.get("source") or "").strip() or "direct",
            "campaign": str(start_context.get("campaign") or "").strip(),
            "referrer_user_id": start_context.get("referrer_user_id"),
            "start_parameter": str(start_context.get("raw_parameter") or "").strip(),
        }
        await monetization_repository.log_event(
            user_id=message.from_user.id,
            event_name="onboarding_started",
            metadata=metadata,
        )
        if metadata["source"] != "direct" or metadata["campaign"] or metadata["referrer_user_id"]:
            await monetization_repository.log_event(
                user_id=message.from_user.id,
                event_name="acquisition_attributed",
                metadata=metadata,
            )

    referrer_user_id = start_context.get("referrer_user_id")
    if referrer_user_id and is_new_user:
        created = await referral_service.register_referral(
            referrer_user_id=referrer_user_id,
            referred_user_id=message.from_user.id,
        )
        if created and referral_settings["referred_welcome_message"]:
            await message.answer(referral_settings["referred_welcome_message"], reply_markup=keyboard)

    if await user_service.is_admin(message.from_user.id):
        await send_welcome(ui_settings["welcome_admin_text"])
        return

    if referrer_user_id and is_new_user:
        await send_user_welcome()
        return

    await send_user_welcome()
