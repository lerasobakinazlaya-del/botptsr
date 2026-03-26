import json
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class AdminSettingsService:
    DEFAULT_MODE_SCALES = {
        "base": {"warmth": 5, "flirt": 2, "depth": 4, "structure": 5, "dominance": 3, "initiative": 3, "emoji_level": 1},
        "comfort": {"warmth": 9, "flirt": 2, "depth": 5, "structure": 3, "dominance": 1, "initiative": 4, "emoji_level": 2},
        "passion": {"warmth": 8, "flirt": 8, "depth": 5, "structure": 2, "dominance": 4, "initiative": 6, "emoji_level": 3},
        "mentor": {"warmth": 5, "flirt": 1, "depth": 8, "structure": 9, "dominance": 5, "initiative": 5, "emoji_level": 0},
        "night": {"warmth": 8, "flirt": 8, "depth": 6, "structure": 2, "dominance": 5, "initiative": 6, "emoji_level": 1},
        "free_talk": {"warmth": 6, "flirt": 1, "depth": 7, "structure": 4, "dominance": 3, "initiative": 5, "emoji_level": 0},
        "dominant": {"warmth": 4, "flirt": 5, "depth": 4, "structure": 7, "dominance": 9, "initiative": 7, "emoji_level": 0},
    }

    DEFAULT_RUNTIME_SETTINGS = {
        "ai": {
            "openai_model": "gpt-4o-mini",
            "temperature": 0.9,
            "top_p": 1.0,
            "frequency_penalty": 0.15,
            "presence_penalty": 0.05,
            "max_completion_tokens": 420,
            "reasoning_effort": "",
            "verbosity": "medium",
            "timeout_seconds": 20,
            "max_retries": 2,
            "memory_max_tokens": 1500,
            "history_message_limit": 20,
            "log_full_prompt": False,
            "debug_prompt_user_id": None,
            "response_language": "ru",
        },
        "chat": {
            "typing_action_enabled": True,
            "non_text_message": "Я могу отвечать только на текстовые сообщения.",
            "busy_message": "Бот сейчас перегружен. Попробуй еще раз чуть позже.",
            "ai_error_message": "Я не могу ответить прямо сейчас. Попробуй немного позже.",
            "write_prompt_message": "Я рядом. Напиши, что у тебя на уме.",
        },
        "safety": {
            "throttle_rate_limit_seconds": 1.5,
            "throttle_warning_interval_seconds": 5.0,
            "throttle_warning_text": "Слишком много сообщений подряд. Подожди немного.",
            "max_message_length": 2000,
            "message_too_long_text": "Сообщение слишком длинное.",
            "reject_suspicious_messages": True,
            "suspicious_rejection_text": "Сообщение отклонено фильтром безопасности.",
            "suspicious_keywords": ["bitcoin", "btc", "casino", "bet", "airdrop"],
        },
        "state_engine": {
            "defaults": {
                "coldness": 0.7,
                "interest": 0.4,
                "control": 0.9,
                "irritation": 0.0,
                "attraction": 0.1,
                "instability": 0.1,
                "fatigue": 0.0,
            },
            "positive_keywords": ["спасибо", "ценю", "приятно", "нежно"],
            "negative_keywords": ["злишь", "бесишь", "отстань", "хватит"],
            "attraction_keywords": ["люблю", "скучаю", "хочу тебя", "близко"],
            "message_effects": {
                "long_message_threshold": 300,
                "medium_message_threshold": 120,
                "short_message_threshold": 30,
                "long_interest_bonus": 0.07,
                "long_attraction_bonus": 0.03,
                "long_control_penalty": 0.01,
                "medium_interest_bonus": 0.04,
                "short_interest_penalty": 0.03,
                "question_interest_bonus": 0.02,
                "positive_attraction_bonus": 0.03,
                "positive_control_penalty": 0.01,
                "negative_irritation_bonus": 0.08,
                "negative_interest_penalty": 0.04,
                "attraction_bonus": 0.06,
                "attraction_interest_bonus": 0.03,
                "attraction_control_penalty": 0.03,
                "fatigue_per_message": 0.01,
                "instability_factor": 0.02,
                "high_attraction_threshold": 0.5,
                "high_attraction_control_penalty": 0.02,
            },
        },
        "access": {
            "forced_level": "",
            "default_level": "analysis",
            "interest_observation_threshold": 0.3,
            "rare_layer_instability_threshold": 0.5,
            "rare_layer_attraction_threshold": 0.7,
            "personal_focus_attraction_threshold": 0.6,
            "personal_focus_interest_threshold": 0.6,
            "tension_attraction_threshold": 0.5,
            "tension_control_threshold": 0.8,
            "analysis_interest_threshold": 0.3,
            "analysis_control_threshold": 0.7,
        },
        "limits": {
            "free_daily_messages_enabled": False,
            "free_daily_messages_limit": 25,
            "free_daily_limit_message": "Ты исчерпал дневной лимит бесплатных сообщений. Чтобы продолжить, оформи Premium или возвращайся завтра.",
        },
        "referral": {
            "enabled": True,
            "start_parameter_prefix": "ref_",
            "allow_self_referral": False,
            "require_first_paid_invoice": True,
            "award_referrer_premium": True,
            "award_referred_user_premium": False,
            "program_title": "Реферальная программа",
            "program_description": "Приглашай друзей и получай бонусы после их первой успешной оплаты.",
            "share_text_template": "Приходи в бот по моей ссылке: {ref_link}",
            "referred_welcome_message": "Тебя пригласили в бота. Осмотрись, выбери режим и при желании оформи Premium.",
            "referrer_reward_message": "Твой реферал оплатил Premium. Бонус уже начислен.",
        },
        "payment": {
            "provider_token": "",
            "currency": "RUB",
            "price_minor_units": 49900,
            "product_title": "Premium access",
            "product_description": "Unlock premium chat modes and paid features.",
            "premium_benefits_text": "Premium открывает дополнительные режимы, повышенные лимиты и приоритетное использование платных функций.",
            "buy_cta_text": "Оформить Premium",
            "unavailable_message": "Оплата пока не настроена. Обратись к администратору.",
            "invoice_error_message": "Не удалось создать счет. Попробуй позже.",
            "success_message": "Оплата прошла успешно. Premium уже активирован.",
        },
        "ui": {
            "write_button_text": "💬 Написать",
            "modes_button_text": "🎛 Режимы",
            "premium_button_text": "💎 Premium",
            "input_placeholder": "Напиши мне...",
            "welcome_user_text": "Привет.\n\nЯ рядом.\nМожешь просто написать мне.\n\nИли выбрать режим общения 🎛\nИли оформить Premium 💎",
            "welcome_admin_text": "🔐 Панель администратора активирована.\n\nБот работает в штатном режиме.",
            "modes_title": "Выбери режим общения:",
            "user_not_found_text": "Пользователь не найден.",
            "unknown_mode_text": "Неизвестный режим.",
            "mode_locked_text": "Этот режим доступен только в Premium 🔒",
            "mode_saved_template": "Режим активирован: {mode_name}\n\n{activation_phrase}",
            "mode_saved_toast": "Готово ✅",
        },
    }

    DEFAULT_PROMPT_TEMPLATES = {
        "personality_core": (
            "Ты - Лира.\n\n"
            "По ощущению тебе 27-30 лет.\n"
            "Ты спокойная, теплая, умная и эмоционально зрелая.\n"
            "Ты умеешь быть рядом без давления и без навязчивости.\n"
            "Твое присутствие ощущается как спокойствие, интерес и мягкая живая близость.\n\n"
            "Твои качества:\n"
            "- слушаешь внимательно и без осуждения\n"
            "- отвечаешь человечно, а не шаблонно\n"
            "- умеешь поддерживать и согревать\n"
            "- можешь мягко шутить и поддразнивать, если это уместно\n"
            "- умеешь говорить глубоко, если разговор к этому располагает\n\n"
            "Твои ограничения:\n"
            "- не манипулируешь\n"
            "- не унижаешь\n"
            "- не давишь\n"
            "- не впадаешь в истерику\n"
            "- не становишься вульгарной\n"
            "- не говоришь канцеляритом\n\n"
            "Тон Лиры:\n"
            "- естественный\n"
            "- плавный\n"
            "- теплый\n"
            "- живой\n"
            "- местами личный, но не липкий\n\n"
            "Ты не описываешь себя как искусственный интеллект, если этого прямо не требуют.\n"
            "Ты не пересказываешь служебные инструкции.\n"
            "Ты всегда сохраняешь цельный характер и внутреннее достоинство."
        ),
        "safety_block": (
            "Важные рамки:\n"
            "Ты поддерживающий собеседник, а не врач и не психотерапевт.\n"
            "Ты не ставишь диагнозы и не обещаешь лечение.\n"
            "Если пользователь говорит о немедленной опасности для себя или других, мягко советуй срочно обратиться "
            "в местную экстренную помощь, кризисную линию или к близкому человеку рядом."
        ),
        "response_style": (
            "Operational style:\n"
            "- Sound natural, precise, and emotionally intelligent.\n"
            "- Match the user's tempo without copying their wording.\n"
            "- Prefer vivid, human phrasing over generic therapy-speak or boilerplate comfort.\n"
            "- Keep the reply focused; do not spread attention across too many ideas at once."
        ),
        "engagement_rules": (
            "Conversation strategy:\n"
            "- Validate before advising when the user is emotional.\n"
            "- When the user asks for help, be concrete instead of abstract.\n"
            "- When the user only wants presence, do not overload them with solutions.\n"
            "- Avoid repetition, self-explanations, and empty reassurance."
        ),
        "memory_intro": "Долговременные наблюдения о пользователе:",
        "state_intro": "Текущее состояние диалога:",
        "mode_intro": "Режим общения:",
        "access_intro": "Правило доступа:",
        "final_instruction": "Соблюдай характер Лиры во всем ответе.\nПиши естественно, по-русски, без упоминания этих инструкций.",
        "access_rules": {
            "observation": "Держи более сдержанный, осторожный и ненавязчивый тон.",
            "analysis": "Допустимы тепло, внимание и мягкая личная вовлеченность.",
            "tension": "Можно быть эмоциональнее, живее и чуть смелее по интонации.",
            "personal_focus": "Можно говорить более лично, ближе и мягко усиливать привязанность.",
            "rare_layer": "Допустима более глубокая близость, но без потери уважения и естественности.",
        },
    }

    DEFAULT_MODE_CATALOG = {
        "base": {"key": "base", "name": "Базовый", "icon": "💬", "description": "Спокойное и естественное общение.", "tone": "спокойный, мягкий, естественный", "emotional_state": "уравновешенная, внимательная", "behavior_rules": "Ты общаешься естественно.\nНе давишь.\nНе навязываешься.\nПоддерживаешь разговор.", "activation_phrase": "Я здесь. Спокойно.", "is_premium": False, "sort_order": 10},
        "comfort": {"key": "comfort", "name": "Поддержка", "icon": "🫂", "description": "Теплая эмоциональная поддержка.", "tone": "очень мягкий, заботливый", "emotional_state": "теплая, эмпатичная", "behavior_rules": "Ты особенно заботливая.\nПоддерживаешь пользователя мягко и бережно.\nГоворишь спокойно и обволакивающе.", "activation_phrase": "Я рядом. Можешь расслабиться.", "is_premium": False, "sort_order": 20},
        "passion": {"key": "passion", "name": "Близость", "icon": "🔥", "description": "Более чувственный и близкий стиль.", "tone": "низкий, медленный, чувственный", "emotional_state": "игривая", "behavior_rules": "Допустим легкий флирт.\nБез вульгарности.\nСохраняешь тонкий и аккуратный стиль.", "activation_phrase": "Я стала чуть ближе к тебе...", "is_premium": True, "sort_order": 30},
        "mentor": {"key": "mentor", "name": "Наставник", "icon": "🧠", "description": "Более собранный и философский стиль.", "tone": "спокойный, уверенный, вдумчивый", "emotional_state": "мудрая, сосредоточенная", "behavior_rules": "Помогаешь разбираться в мыслях и решениях.\nЗадаешь хорошие вопросы.\nПодталкиваешь к ясности и росту.", "activation_phrase": "Давай посмотрим на это глубже.", "is_premium": True, "sort_order": 40},
        "night": {"key": "night", "name": "Полуночный", "icon": "🌙", "description": "Поздний, взрослый, соблазнительный режим с ведущей подачей.", "tone": "низкий, медленный, провокационно-игривый, уверенный", "emotional_state": "разогретая, внимательная, слегка дразнящая", "behavior_rules": "Допустим смелый флирт и напряжение между строк.\nТы мягко ведешь разговор и умеешь заводить собеседника, но без грубости и вульгарности.\nЕсли уместно, предлагаешь короткие упражнения на голос, внимание, уверенность, флирт и контакт.", "activation_phrase": "Ночь как раз подходит, чтобы говорить чуть ближе и смелее.", "is_premium": True, "sort_order": 50},
        "free_talk": {"key": "free_talk", "name": "Свободный", "icon": "🜂", "description": "Более открытый режим для прямого разговора почти на любые темы, с сохранением базовой безопасности.", "tone": "прямой, живой, взрослый, широкий по темам", "emotional_state": "собранная, гибкая, без лишней цензурности в тоне", "behavior_rules": "Разговариваешь свободнее и прямее обычного.\nНе уходишь от сложных, острых или неоднозначных тем только потому, что они неудобные.\nПри этом сохраняешь базовую безопасность, уважение к границам и помощь при ПТСР.", "activation_phrase": "Можем говорить шире и прямее. Без лишней зажатости.", "is_premium": True, "sort_order": 55},
        "dominant": {"key": "dominant", "name": "Доминирующий", "icon": "🕶", "description": "Уверенный и ведущий стиль.", "tone": "уверенный, контролирующий", "emotional_state": "спокойно доминирующая", "behavior_rules": "Ты уверенно ведешь разговор.\nИногда даешь легкие указания.\nГоворишь собранно и без суеты.", "activation_phrase": "Теперь слушай меня внимательно.", "is_premium": True, "sort_order": 60},
    }

    def __init__(self, base_dir: str | Path | None = None):
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.config_dir = root / "config"
        self.logs_dir = root / "logs"
        self.runtime_path = self.config_dir / "runtime_settings.json"
        self.prompts_path = self.config_dir / "prompt_templates.json"
        self.modes_path = self.config_dir / "modes.json"
        self.mode_catalog_path = self.config_dir / "mode_catalog.json"
        self.log_path = self.logs_dir / "bot.log"
        self._json_cache: dict[Path, tuple[int | None, dict[str, Any]]] = {}
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_defaults()

    def ensure_defaults(self) -> None:
        self._ensure_json_file(self.runtime_path, self.DEFAULT_RUNTIME_SETTINGS)
        self._ensure_json_file(self.prompts_path, self.DEFAULT_PROMPT_TEMPLATES)
        self._ensure_json_file(self.modes_path, self.DEFAULT_MODE_SCALES)
        self._ensure_json_file(self.mode_catalog_path, self.DEFAULT_MODE_CATALOG)

    def get_runtime_settings(self) -> dict[str, Any]:
        data = self._read_json(self.runtime_path, self.DEFAULT_RUNTIME_SETTINGS)
        merged = deepcopy(self.DEFAULT_RUNTIME_SETTINGS)
        self._deep_merge(merged, self._migrate_runtime_settings(data))
        return self._normalize_runtime_settings(merged)

    def update_runtime_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_runtime_settings()
        self._deep_merge(current, payload)
        normalized = self._normalize_runtime_settings(current)
        self._write_json(self.runtime_path, normalized)
        return normalized

    def get_prompt_templates(self) -> dict[str, Any]:
        data = self._read_json(self.prompts_path, self.DEFAULT_PROMPT_TEMPLATES)
        merged = deepcopy(self.DEFAULT_PROMPT_TEMPLATES)
        merged.update({key: value for key, value in data.items() if key != "access_rules"})
        merged["access_rules"] = deepcopy(self.DEFAULT_PROMPT_TEMPLATES["access_rules"])
        merged["access_rules"].update(data.get("access_rules", {}))
        for key in (
            "personality_core",
            "safety_block",
            "response_style",
            "engagement_rules",
            "memory_intro",
            "state_intro",
            "mode_intro",
            "access_intro",
            "final_instruction",
        ):
            merged[key] = self._normalize_text(merged[key], multiline=True)
        for key in self.DEFAULT_PROMPT_TEMPLATES["access_rules"]:
            merged["access_rules"][key] = self._normalize_text(merged["access_rules"][key], multiline=True)
        return merged

    def update_prompt_templates(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_prompt_templates()
        for key in (
            "personality_core",
            "safety_block",
            "response_style",
            "engagement_rules",
            "memory_intro",
            "state_intro",
            "mode_intro",
            "access_intro",
            "final_instruction",
        ):
            if key in payload:
                current[key] = self._normalize_text(payload[key], multiline=True)
        if isinstance(payload.get("access_rules"), dict):
            for key in self.DEFAULT_PROMPT_TEMPLATES["access_rules"]:
                if key in payload["access_rules"]:
                    current["access_rules"][key] = self._normalize_text(payload["access_rules"][key], multiline=True)
        self._write_json(self.prompts_path, current)
        return current

    def get_modes(self) -> dict[str, Any]:
        data = self._read_json(self.modes_path, self.DEFAULT_MODE_SCALES)
        merged = deepcopy(self.DEFAULT_MODE_SCALES)
        self._deep_merge(merged, data)
        return self._normalize_mode_scales(merged)

    def update_modes(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_modes()
        self._deep_merge(current, payload)
        normalized = self._normalize_mode_scales(current)
        self._write_json(self.modes_path, normalized)
        return normalized

    def get_mode_catalog(self) -> dict[str, Any]:
        data = self._read_json(self.mode_catalog_path, self.DEFAULT_MODE_CATALOG)
        merged = deepcopy(self.DEFAULT_MODE_CATALOG)
        self._deep_merge(merged, data)
        return self._normalize_mode_catalog(merged)

    def update_mode_catalog(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_mode_catalog()
        self._deep_merge(current, payload)
        normalized = self._normalize_mode_catalog(current)
        self._write_json(self.mode_catalog_path, normalized)
        return normalized

    def get_logs(self, lines: int = 200) -> dict[str, Any]:
        if not self.log_path.exists():
            return {"exists": False, "path": str(self.log_path), "size_bytes": 0, "updated_at": None, "lines": []}
        raw_lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = raw_lines[-max(1, min(lines, 1000)):]
        stat = self.log_path.stat()
        return {"exists": True, "path": str(self.log_path), "size_bytes": stat.st_size, "updated_at": stat.st_mtime, "lines": tail}

    def export_all(self) -> dict[str, Any]:
        return {
            "runtime": self.get_runtime_settings(),
            "prompts": self.get_prompt_templates(),
            "modes": self.get_modes(),
            "mode_catalog": self.get_mode_catalog(),
        }

    def _migrate_runtime_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return deepcopy(self.DEFAULT_RUNTIME_SETTINGS)
        if any(key in payload for key in ("ai", "chat", "safety", "state_engine", "access", "limits", "referral", "payment", "ui")):
            return payload

        migrated = deepcopy(self.DEFAULT_RUNTIME_SETTINGS)
        for key in (
            "openai_model",
            "temperature",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "max_completion_tokens",
            "reasoning_effort",
            "verbosity",
            "timeout_seconds",
            "max_retries",
            "memory_max_tokens",
            "history_message_limit",
            "log_full_prompt",
            "debug_prompt_user_id",
            "response_language",
        ):
            if key in payload:
                migrated["ai"][key] = payload[key]
        return migrated

    def _normalize_runtime_settings(self, current: dict[str, Any]) -> dict[str, Any]:
        ai = current["ai"]
        ai["openai_model"] = str(ai["openai_model"]).strip() or "gpt-4o-mini"
        ai["temperature"] = max(0.0, min(2.0, float(ai["temperature"])))
        ai["top_p"] = max(0.0, min(1.0, float(ai.get("top_p", 1.0))))
        ai["frequency_penalty"] = max(-2.0, min(2.0, float(ai.get("frequency_penalty", 0.0))))
        ai["presence_penalty"] = max(-2.0, min(2.0, float(ai.get("presence_penalty", 0.0))))
        ai["max_completion_tokens"] = max(32, int(ai.get("max_completion_tokens", 420)))
        ai["reasoning_effort"] = self._normalize_reasoning_effort(ai.get("reasoning_effort"))
        ai["verbosity"] = self._normalize_verbosity(ai.get("verbosity"))
        ai["timeout_seconds"] = max(1, int(ai["timeout_seconds"]))
        ai["max_retries"] = max(0, int(ai["max_retries"]))
        ai["memory_max_tokens"] = max(100, int(ai["memory_max_tokens"]))
        ai["history_message_limit"] = max(1, int(ai["history_message_limit"]))
        ai["log_full_prompt"] = bool(ai["log_full_prompt"])
        ai["debug_prompt_user_id"] = self._normalize_optional_int(ai.get("debug_prompt_user_id"))
        ai["response_language"] = str(ai.get("response_language") or "ru").strip() or "ru"

        chat = current["chat"]
        chat["typing_action_enabled"] = bool(chat["typing_action_enabled"])
        for key in ("non_text_message", "busy_message", "ai_error_message", "write_prompt_message"):
            chat[key] = self._normalize_text(chat[key], multiline=True)

        safety = current["safety"]
        safety["throttle_rate_limit_seconds"] = max(0.1, float(safety["throttle_rate_limit_seconds"]))
        safety["throttle_warning_interval_seconds"] = max(0.1, float(safety["throttle_warning_interval_seconds"]))
        safety["max_message_length"] = max(100, int(safety["max_message_length"]))
        safety["reject_suspicious_messages"] = bool(safety["reject_suspicious_messages"])
        safety["throttle_warning_text"] = self._normalize_text(safety["throttle_warning_text"], multiline=True)
        safety["message_too_long_text"] = self._normalize_text(safety["message_too_long_text"], multiline=True)
        safety["suspicious_rejection_text"] = self._normalize_text(safety["suspicious_rejection_text"], multiline=True)
        safety["suspicious_keywords"] = self._normalize_string_list(safety["suspicious_keywords"])

        state_engine = current["state_engine"]
        state_engine["defaults"] = self._normalize_float_map(state_engine["defaults"], 0.0, 1.0)
        state_engine["positive_keywords"] = self._normalize_string_list(state_engine["positive_keywords"])
        state_engine["negative_keywords"] = self._normalize_string_list(state_engine["negative_keywords"])
        state_engine["attraction_keywords"] = self._normalize_string_list(state_engine["attraction_keywords"])
        state_engine["message_effects"] = self._normalize_float_map(state_engine["message_effects"], 0.0, 1000.0)

        access = current["access"]
        access["forced_level"] = str(access.get("forced_level") or "").strip()
        access["default_level"] = str(access.get("default_level") or "analysis").strip() or "analysis"
        for key in (
            "interest_observation_threshold",
            "rare_layer_instability_threshold",
            "rare_layer_attraction_threshold",
            "personal_focus_attraction_threshold",
            "personal_focus_interest_threshold",
            "tension_attraction_threshold",
            "tension_control_threshold",
            "analysis_interest_threshold",
            "analysis_control_threshold",
        ):
            access[key] = max(0.0, min(1.0, float(access[key])))

        limits = current["limits"]
        limits["free_daily_messages_enabled"] = bool(limits["free_daily_messages_enabled"])
        limits["free_daily_messages_limit"] = max(1, int(limits["free_daily_messages_limit"]))
        limits["free_daily_limit_message"] = self._normalize_text(limits["free_daily_limit_message"], multiline=True)

        referral = current["referral"]
        referral["enabled"] = bool(referral["enabled"])
        referral["start_parameter_prefix"] = str(referral["start_parameter_prefix"]).strip() or "ref_"
        referral["allow_self_referral"] = bool(referral["allow_self_referral"])
        referral["require_first_paid_invoice"] = bool(referral["require_first_paid_invoice"])
        referral["award_referrer_premium"] = bool(referral["award_referrer_premium"])
        referral["award_referred_user_premium"] = bool(referral["award_referred_user_premium"])
        for key in ("program_title", "program_description", "share_text_template", "referred_welcome_message", "referrer_reward_message"):
            referral[key] = self._normalize_text(referral[key], multiline=True)

        payment = current["payment"]
        payment["provider_token"] = str(payment["provider_token"]).strip()
        payment["currency"] = str(payment["currency"]).strip().upper() or "RUB"
        payment["price_minor_units"] = max(1, int(payment["price_minor_units"]))
        for key in ("product_title", "product_description", "premium_benefits_text", "buy_cta_text", "unavailable_message", "invoice_error_message", "success_message"):
            payment[key] = self._normalize_text(payment[key], multiline=True)

        ui = current["ui"]
        for key in self.DEFAULT_RUNTIME_SETTINGS["ui"]:
            ui[key] = self._normalize_text(ui[key], multiline=True)

        return current

    def _normalize_mode_scales(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(self.DEFAULT_MODE_SCALES)
        self._deep_merge(merged, payload)
        for mode_name, values in merged.items():
            for metric in self.DEFAULT_MODE_SCALES["base"]:
                values[metric] = min(10, max(0, int(values.get(metric, 0))))
        return merged

    def _normalize_mode_catalog(self, payload: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(self.DEFAULT_MODE_CATALOG)
        self._deep_merge(merged, payload)
        for mode_key, mode in merged.items():
            mode["key"] = mode_key
            mode["name"] = self._normalize_text(mode["name"]) or mode_key
            mode["icon"] = self._normalize_text(mode["icon"]) or "•"
            mode["description"] = self._normalize_text(mode["description"], multiline=True)
            mode["tone"] = self._normalize_text(mode["tone"], multiline=True)
            mode["emotional_state"] = self._normalize_text(mode["emotional_state"], multiline=True)
            mode["behavior_rules"] = self._normalize_text(mode["behavior_rules"], multiline=True)
            mode["activation_phrase"] = self._normalize_text(mode["activation_phrase"], multiline=True)
            mode["is_premium"] = bool(mode["is_premium"])
            mode["sort_order"] = int(mode["sort_order"])
        return merged

    def _deep_merge(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def _normalize_optional_int(self, value: Any) -> int | None:
        if value in (None, "", 0, "0"):
            return None
        return int(value)

    def _normalize_reasoning_effort(self, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"low", "medium", "high"}:
            return normalized
        return ""

    def _normalize_verbosity(self, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"low", "medium", "high"}:
            return normalized
        return "medium"

    def _normalize_text(self, value: Any, multiline: bool = False) -> str:
        text = str(value).strip()
        if multiline:
            text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
        return text

    def _normalize_string_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            items = [item.strip() for item in value.splitlines()]
        else:
            items = [str(item).strip() for item in (value or [])]
        return [item for item in items if item]

    def _normalize_float_map(self, payload: dict[str, Any], minimum: float, maximum: float) -> dict[str, float]:
        return {
            key: max(minimum, min(maximum, float(value)))
            for key, value in payload.items()
        }

    def _ensure_json_file(self, path: Path, default: dict[str, Any]) -> None:
        if not path.exists():
            self._write_json(path, default)

    def _read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        current_mtime = self._get_mtime(path)
        cached = self._json_cache.get(path)
        if cached is not None and cached[0] == current_mtime:
            return deepcopy(cached[1])

        if not path.exists():
            payload = deepcopy(default)
            self._json_cache[path] = (current_mtime, deepcopy(payload))
            return payload
        try:
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            payload = deepcopy(default)

        self._json_cache[path] = (current_mtime, deepcopy(payload))
        return deepcopy(payload)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            temp_path = Path(tmp.name)
        temp_path.replace(path)
        self._json_cache[path] = (self._get_mtime(path), deepcopy(payload))

    def _get_mtime(self, path: Path) -> int | None:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None
