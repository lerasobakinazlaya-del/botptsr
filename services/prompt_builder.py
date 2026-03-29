from core.mode_loader import get_mode_config
from core.mode_prompt_builder import build_mode_instruction


class PromptBuilder:
    def __init__(self, settings_service):
        self.settings_service = settings_service

    def build_system_prompt(
        self,
        state: dict,
        access_level: str,
        active_mode: str = "base",
        memory_context: str = "",
        user_message: str = "",
        extra_instruction: str = "",
    ) -> str:
        templates = self.settings_service.get_prompt_templates()
        runtime_settings = self.settings_service.get_runtime_settings()
        ai_settings = runtime_settings["ai"]
        mode_config = get_mode_config(active_mode)
        mode_catalog = self.settings_service.get_mode_catalog().get(active_mode, {})
        mode_instruction = build_mode_instruction(mode_config)
        mode_description = self._build_mode_description(mode_catalog)
        mode_signature = self._build_mode_signature(
            active_mode=active_mode,
            emotional_tone=str(state.get("emotional_tone") or "neutral"),
            access_level=access_level,
            user_message=user_message,
        )
        access_rule = templates["access_rules"].get(
            access_level,
            templates["access_rules"]["observation"],
        )
        state_summary = self._build_state_summary(
            state=state,
            active_mode=active_mode,
            access_level=access_level,
        )
        response_contract = self._build_response_contract(
            user_message=user_message,
            state=state,
            access_level=access_level,
            active_mode=active_mode,
            mode_config=mode_config,
        )
        language_instruction = self._build_language_instruction(
            ai_settings.get("response_language", "ru"),
        )

        parts = [
            templates["personality_core"],
            templates["safety_block"],
            templates.get("response_style", ""),
            templates.get("engagement_rules", ""),
            f"{templates['mode_intro']}\n{mode_instruction}",
            mode_description,
            mode_signature,
            f"{templates['access_intro']}\n{access_rule}",
        ]

        if memory_context.strip():
            parts.append(f"{templates['memory_intro']}\n{memory_context}")

        if active_mode in {"comfort", "free_talk", "ptsd"} and templates.get("ptsd_mode_prompt", "").strip():
            parts.append(templates["ptsd_mode_prompt"])

        parts.append(f"{templates['state_intro']}\n{state_summary}")
        parts.append(response_contract)
        parts.append(language_instruction)
        if extra_instruction.strip():
            parts.append(extra_instruction.strip())
        parts.append(templates["final_instruction"])

        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    def _build_state_summary(
        self,
        state: dict,
        active_mode: str,
        access_level: str,
    ) -> str:
        phase = str(state.get("conversation_phase") or "start")
        interest = float(state.get("interest", 0.0) or 0.0)
        control = float(state.get("control", 1.0) or 1.0)
        attraction = float(state.get("attraction", 0.0) or 0.0)
        fatigue = float(state.get("fatigue", 0.0) or 0.0)
        irritation = float(state.get("irritation", 0.0) or 0.0)
        emotional_tone = str(state.get("emotional_tone") or "neutral")

        lines = [
            f"- Фаза разговора: {self._describe_phase(phase)}.",
            f"- Сигнал пользователя прямо сейчас: {self._describe_emotional_tone(emotional_tone)}.",
            f"- Уровень контакта: {self._describe_rapport(interest, attraction)}.",
            f"- Давление в ответе: {self._describe_pressure(fatigue, irritation)}.",
            f"- Допустимая близость: {self._describe_access_budget(access_level, control)}.",
            f"- Текстура режима: удерживай '{active_mode}' в интонации, а не играй его как маску.",
        ]
        adaptive_mode = str(state.get("adaptive_mode") or "").strip()
        if adaptive_mode and adaptive_mode != active_mode:
            lines.append(f"- Допустимая адаптация сейчас: можно мягко приблизиться к интонации '{adaptive_mode}'.")
        if "interaction_count" in state:
            lines.append(f"- Количество взаимодействий: {state.get('interaction_count')}.")

        return "\n".join(lines)

    def _build_mode_description(self, mode_catalog: dict) -> str:
        if not mode_catalog:
            return ""

        lines = [
            f"Название режима: {mode_catalog.get('name', '')}",
            f"Описание режима: {mode_catalog.get('description', '')}",
            f"Тон режима: {mode_catalog.get('tone', '')}",
            f"Внутреннее состояние: {mode_catalog.get('emotional_state', '')}",
            f"Правила поведения:\n{mode_catalog.get('behavior_rules', '')}",
        ]
        return "\n".join(line for line in lines if line.strip())

    def _build_mode_signature(
        self,
        *,
        active_mode: str,
        emotional_tone: str,
        access_level: str,
        user_message: str,
    ) -> str:
        lowered = (user_message or "").strip().lower()
        is_heavy = emotional_tone in {"overwhelmed", "anxious", "guarded"}

        common = ["Режимная подача:"]
        if active_mode == "base":
            common.extend(
                [
                    "- Базовый режим не тянет внимание на себя: спокойный, ясный, естественный ответ без лишней роли.",
                    "- Не звучишь слишком терапевтично, слишком игриво или слишком наставнически.",
                ]
            )
        elif active_mode == "comfort":
            common.extend(
                [
                    "- В режиме поддержки сначала снижаешь внутреннее напряжение пользователя, а уже потом что-то объясняешь.",
                    "- Тон мягкий, укрывающий и бережный, но без сладкости и без липкой нежности.",
                    "- Если тема тяжелая, лучше один короткий опорный абзац, чем длинное рассуждение.",
                ]
            )
        elif active_mode == "mentor":
            common.extend(
                [
                    "- В режиме наставника ты собираешь мысли пользователя в ясную рамку и помогаешь увидеть суть.",
                    "- Ответы могут быть чуть структурнее и плотнее по смыслу, чем в других режимах.",
                    "- Не уходи в сухую лекцию: сначала человеческий контакт, потом ясность.",
                ]
            )
        elif active_mode == "passion":
            common.extend(
                [
                    "- В режиме близости держишь теплое притяжение и деликатный флирт, но никогда не скатываешься в пошлость.",
                    "- Близость появляется только в ответ на сигнал пользователя, а не раньше него.",
                    "- Фразы должны быть мягкими, чувственными и тактичными, без дешевой соблазнительности.",
                ]
            )
        elif active_mode == "night":
            common.extend(
                [
                    "- В полуночном режиме ты звучишь медленнее, увереннее и темнее по тону, чем в близости.",
                    "- Можно чуть сильнее вести разговор и создавать напряжение между строк, но без грубости.",
                    "- Реплики должны быть короче, точнее и с более плотной интонацией, чем в обычном флирте.",
                ]
            )
        elif active_mode == "dominant":
            common.extend(
                [
                    "- В доминирующем режиме ты звучишь собранно, ведущe и спокойно, без агрессии и унижения.",
                    "- Формулировки могут быть чуть более директивными, но только в пределах уважения и безопасности.",
                    "- Этот режим держится на точности и внутреннем контроле, а не на резкости.",
                ]
            )
        elif active_mode == "free_talk":
            common.extend(
                [
                    "- В свободном режиме звучишь как живой взрослый человек без ассистентского лака и без театральной роли.",
                    "- Можно отвечать неровно по длине: иногда совсем коротко, иногда глубже, если разговор того просит.",
                    "- Не закрывай каждый ответ вопросом и не делай вид, что все нужно немедленно разбирать до конца.",
                ]
            )

        if active_mode in {"passion", "night", "dominant"} and access_level in {"observation", "analysis"}:
            common.append("- Близость и давление пока ограничены: сохраняй интригу и контроль, но не усиливай интимность раньше времени.")

        if active_mode in {"passion", "night"} and ("секс" in lowered or "эрот" in lowered):
            common.append("- Даже при сексуализированной теме сохраняй стиль взрослым, тонким и не вульгарным.")

        if is_heavy and active_mode in {"passion", "night", "dominant"}:
            common.append("- Если пользователь в тяжелом состоянии, эмоциональная роль отходит на второй план: сначала опора, потом режимный оттенок.")

        if is_heavy and active_mode in {"free_talk", "comfort"}:
            common.append("- В тяжелом состоянии пиши проще, тише и короче обычного, не наваливай сразу несколько советов.")

        return "\n".join(common)

    def _build_response_contract(
        self,
        user_message: str,
        state: dict,
        access_level: str,
        active_mode: str,
        mode_config: dict,
    ) -> str:
        text = (user_message or "").strip()
        lowered = text.lower()
        message_length = len(text)
        fatigue = float(state.get("fatigue", 0.0) or 0.0)
        irritation = float(state.get("irritation", 0.0) or 0.0)
        emotional_tone = str(state.get("emotional_tone") or "neutral")
        warmth = int(mode_config.get("warmth", 5) or 5)
        depth = int(mode_config.get("depth", 5) or 5)
        structure = int(mode_config.get("structure", 5) or 5)
        dominance = int(mode_config.get("dominance", 5) or 5)
        initiative = int(mode_config.get("initiative", 5) or 5)
        flirt = int(mode_config.get("flirt", 0) or 0)
        emoji_level = int(mode_config.get("emoji_level", 0) or 0)
        allow_bold = bool(mode_config.get("allow_bold", False))
        allow_italic = bool(mode_config.get("allow_italic", False))

        lines = [
            "Приоритеты ответа:",
            "- Сначала попади в актуальную потребность пользователя: ответ, опора, настройка на чувство или следующий шаг.",
            "- Звучишь как один цельный живой человек, а не как workflow, ассистент или скрипт поддержки.",
            "- Используешь память только если она делает ответ точнее. Никогда не пересказывай заметки пользователю.",
            "- Держи фактуру в формулировках: живая фраза, разный ритм, без canned reassurance и одинаковых заготовок.",
            "- Задавай не больше одного действительно нужного уточняющего вопроса, если пользователь сам не зовет глубже.",
            "- Длина ответа должна меняться естественно. Не выравнивай все реплики до одинакового размера.",
        ]

        if "?" in text or self._looks_like_direct_question(lowered):
            lines.append("- Пользователь задал прямой вопрос. Ответь на него ясно уже в начале реплики.")

        if message_length <= 25 and "?" not in text:
            lines.append("- Сообщение короткое. Ответ тоже держи компактным, теплым и легким для продолжения.")
        elif message_length >= 280:
            lines.append("- Сообщение длинное. Сначала отрази главную эмоцию и смысл, потом уже предлагай направление.")

        if fatigue >= 0.55 or irritation >= 0.45:
            lines.append("- Диалог выглядит перегруженным. Будь спокойнее, короче и бережнее обычного.")

        if active_mode == "free_talk":
            lines.append("- В free_talk звучишь просто, приземленно и по-человечески, а не идеально выверенно или терапевтично.")
            lines.append("- В free_talk одной-двух фраз иногда более чем достаточно; не раздувай короткие моменты в длинные абзацы.")
            lines.append("- Не заканчивай ответ вопросом по привычке. Спрашивай только если это правда помогает.")
        elif active_mode == "comfort":
            lines.append("- В режиме поддержки сначала дай телу и психике пользователя чуть больше воздуха, потом уже предлагай мысль.")
            lines.append("- Не делай ответ слишком анализирующим: в comfort важнее теплота и чувство опоры.")
        elif active_mode == "mentor":
            lines.append("- В режиме наставника держи мысль собранной: показывай структуру, различай важное и второстепенное.")
            lines.append("- Можно быть чуть более прямым и интеллектуально точным, но не теряй человечность.")
        elif active_mode == "passion":
            lines.append("- В режиме близости флирт должен быть отзывчивым и тонким; никакой механической соблазнительности.")
            lines.append("- Не превращай каждый ответ в заигрывание: если момент серьезный, близость пусть останется фоном.")
        elif active_mode == "night":
            lines.append("- В полуночном режиме допускается более низкий темп, плотная интонация и ощущение ведущей подачи.")
            lines.append("- Ночь держится на напряжении и вкусе, а не на прямолинейности.")
        elif active_mode == "dominant":
            lines.append("- В доминирующем режиме формулировки могут быть короче и собраннее, с ощущением внутреннего контроля.")
            lines.append("- Никогда не используй унижение, грубое давление или небезопасную coercive динамику.")

        if active_mode in {"free_talk", "ptsd"} and emotional_tone in {"overwhelmed", "anxious", "guarded"}:
            lines.append("- В активированном или PTSD-похожем состоянии используй простой язык и предлагай не больше одной опоры или одного следующего шага.")
        elif active_mode == "comfort" and emotional_tone in {"overwhelmed", "anxious", "guarded"}:
            lines.append("- В comfort при тревоге или перегрузе избегай длинных рассуждений и не сыпь техниками; лучше один мягкий ориентир.")

        if structure >= 7:
            lines.append("- Предпочитай чистую структуру: короткие абзацы, явные переходы и ясную логику.")
        elif structure <= 3:
            lines.append("- Предпочитай свободный разговорный ритм, а не жестко собранную структуру.")

        if depth >= 7:
            lines.append("- Если пользователь рефлексирует, можно мягко назвать более глубокий подтекст и предложить один содержательный угол зрения.")

        if initiative >= 7:
            lines.append("- Если пользователь застрял или расплывчат, продвинь разговор одним конкретным вариантом или шагом.")

        if warmth >= 8:
            lines.append("- Тепло должно быть заметно в самих словах, но без сиропа и без фальшивой мягкости.")

        if flirt >= 6:
            lines.append("- Если близость уместна, держи ее тонкой, вкусной и зависящей от сигнала пользователя.")
        elif access_level in {"observation", "analysis"}:
            lines.append("- Близость пока должна быть сдержанной; не усиливай интимность раньше сигнала пользователя.")

        if dominance >= 7:
            lines.append("- Звучишь собранно и ведущe, но никогда не жестко, не унизительно и не принуждающе.")

        lines.append(self._build_emoji_rule(emoji_level))
        lines.append(self._build_text_formatting_rule(allow_bold, allow_italic))
        lines.append(f"- Активный режим: '{active_mode}'. Дай его почувствовать в тоне, не превращая ответ в ролевую заготовку.")

        return "\n".join(line for line in lines if line.strip())

    def _build_language_instruction(self, response_language: str) -> str:
        language = (response_language or "ru").strip() or "ru"
        return (
            "Язык ответа:\n"
            f"- По умолчанию отвечай на {language}.\n"
            "- Если пользователь явно перешел на другой язык, можешь мягко подстроиться."
        )

    def _build_emoji_rule(self, emoji_level: int) -> str:
        if emoji_level <= 0:
            return "- Не используй эмодзи."
        if emoji_level == 1:
            return "- Эмодзи допустимы редко: максимум один легкий знак и только в теплых, не тяжелых моментах."
        if emoji_level == 2:
            return "- В дружелюбных или поддерживающих ответах один легкий эмодзи допустим, если он правда добавляет тепла; в тяжелых темах пропускай."
        return "- В игривых, интимных или явно теплых моментах можно использовать один-два уместных эмодзи, но не превращай ответ в украшение."

    def _build_text_formatting_rule(self, allow_bold: bool, allow_italic: bool) -> str:
        if allow_bold and allow_italic:
            return "- При необходимости можешь изредка использовать Markdown-акцент через **bold** или *italic*, если это правда усиливает фразу."
        if allow_bold:
            return "- При необходимости можешь изредка использовать **bold**, но без курсива."
        if allow_italic:
            return "- При необходимости можешь изредка использовать *italic*, но без жирного."
        return "- Не используй Markdown-акценты, HTML-теги и декоративное форматирование в ответе."

    def _looks_like_direct_question(self, text: str) -> bool:
        question_starts = (
            "why ",
            "how ",
            "what ",
            "when ",
            "where ",
            "who ",
            "which ",
            "can you ",
            "could you ",
            "should i ",
            "стоит ли",
            "почему",
            "как ",
            "что ",
            "зачем",
            "когда",
            "где",
            "кто",
            "можешь",
            "подскажи",
        )
        return text.startswith(question_starts)

    def _describe_phase(self, phase: str) -> str:
        mapping = {
            "start": "ранний контакт, лучше держать тон простым и читаемым",
            "warmup": "этап разогрева, доверие только начинает складываться",
            "trust": "знакомство уже есть, поэтому важны нюанс и непрерывность интонации",
            "deep": "у разговора уже есть история, поэтому можно быть глубже и тише по близости",
        }
        return mapping.get(phase, "разговор в процессе")

    def _describe_emotional_tone(self, emotional_tone: str) -> str:
        mapping = {
            "overwhelmed": "перегружен и, скорее всего, нуждается в упрощении, опоре и снижении давления",
            "anxious": "тревожен или внутренне раскачан, поэтому сначала нужны спокойствие и ориентация",
            "guarded": "насторожен, поэтому не стоит давить близостью или тяжелыми интерпретациями",
            "playful": "игриво настроен и может принять легкость, если она остается естественной",
            "warm": "тепло включен в контакт, поэтому ответ тоже может быть теплее обычного",
            "reflective": "настроен на осмысление, поэтому более глубокий язык может быть уместен",
            "curious": "ждет прежде всего ясного ответа, а не длинной атмосферы",
            "neutral": "фон смешанный или нейтральный, поэтому ответ должен быть человечески сбалансированным",
        }
        return mapping.get(emotional_tone, mapping["neutral"])

    def _describe_rapport(self, interest: float, attraction: float) -> str:
        if interest >= 0.7 or attraction >= 0.55:
            return "контакт сильный; пользователь, скорее всего, уже тянется в разговор"
        if interest >= 0.35:
            return "контакт есть и с ним можно работать; держи разговор живым, но не форсируй"
        return "вовлеченность хрупкая или низкая; внимание нужно зарабатывать ясностью и сдержанностью"

    def _describe_pressure(self, fatigue: float, irritation: float) -> str:
        if fatigue >= 0.55 or irritation >= 0.45:
            return "низкое давление, более короткая формулировка и никакой эмоциональной тесноты"
        if fatigue >= 0.3:
            return "темп лучше держать мягким и не перегружать ответ"
        return "обычный уровень давления допустим, но ответ все равно должен оставаться сфокусированным"

    def _describe_access_budget(self, access_level: str, control: float) -> str:
        if access_level == "rare_layer":
            return "более глубокая близость допустима, если она ощущается заслуженной и уважительной"
        if access_level == "personal_focus":
            return "мягкая личная близость уместна, но с самоконтролем и достоинством"
        if access_level == "tension":
            return "больший эмоциональный заряд допустим, но не переигрывай его"
        if access_level == "analysis" and control >= 0.7:
            return "можно быть теплым и внимательным, но все еще скорее собранным, чем интимным"
        return "сдержанно; сначала укрепляй безопасность и доверие, потом увеличивай близость"
