import unittest

from services.response_guardrails import (
    analyze_response_style,
    apply_human_style_guardrails,
    apply_ptsd_response_guardrails,
    build_crisis_support_response,
    detect_crisis_signal,
    tighten_ptsd_response,
)


class ResponseGuardrailsTests(unittest.TestCase):
    def test_guardrails_replace_canned_phrases_and_limit_questions(self):
        result = apply_ptsd_response_guardrails(
            "Я понимаю, что тебе тяжело. Твои чувства валидны. Что сейчас рядом? Чем помочь?",
            active_mode="comfort",
            emotional_tone="anxious",
            enabled=True,
        )

        self.assertIn("слышу, как тебе тяжело", result.lower())
        self.assertIn("твоя реакция понятна", result.lower())
        self.assertEqual(result.count("?"), 1)

    def test_guardrails_do_not_change_other_modes(self):
        result = apply_ptsd_response_guardrails(
            "Я понимаю, что тебе тяжело. Что сейчас рядом?",
            active_mode="mentor",
            emotional_tone="anxious",
            enabled=True,
        )

        self.assertEqual(result, "Я понимаю, что тебе тяжело. Что сейчас рядом?")

    def test_analyze_response_style_reports_blocked_phrases(self):
        audit = analyze_response_style(
            "Я понимаю, что тебе тяжело. Давай побудем здесь.",
        )

        self.assertEqual(audit["question_count"], 0)
        self.assertEqual(audit["blocked_phrases"], ["я понимаю, что тебе тяжело"])
        self.assertFalse(audit["looks_overloaded"])

    def test_analyze_response_style_flags_overloaded_ptsd_reply(self):
        audit = analyze_response_style(
            "Сейчас попробуем разложить это по шагам. "
            "Сначала обрати внимание на дыхание. "
            "Потом осмотрись вокруг и назови предметы рядом. "
            "После этого попробуй почувствовать пол под ногами. "
            "И затем напиши мне, что изменилось.",
        )

        self.assertEqual(audit["sentence_count"], 5)
        self.assertTrue(audit["looks_overloaded"])

    def test_tighten_ptsd_response_keeps_only_short_core(self):
        result = tighten_ptsd_response(
            "Слышу, как тебе тяжело. "
            "Сейчас не нужно решать всё сразу. "
            "Посмотри вокруг и назови три предмета рядом. "
            "Сделай один медленный выдох длиннее вдоха. "
            "Если хочешь, потом напиши, что стало чуть устойчивее.",
        )

        self.assertLessEqual(len(result), 340)
        self.assertLessEqual(result.count("."), 4)

    def test_human_style_guardrails_strip_low_value_opener_and_generic_question(self):
        result = apply_human_style_guardrails(
            "Это хороший подход. Лучше заранее договориться о стоп-сигнале и утре после. Как ты на это смотришь?",
            answer_first=True,
            allow_follow_up_question=False,
        )

        self.assertEqual(
            result,
            "Лучше заранее договориться о стоп-сигнале и утре после.",
        )

    def test_human_style_guardrails_strip_meta_script_wrapper(self):
        result = apply_human_style_guardrails(
            'Понял. Вот примерный текст: 1. "Что понравилось?" 2. "Что было некомфортно?" Таким образом, вы сможете открыто обсудить все аспекты и лучше понять друг друга.',
            answer_first=True,
            allow_follow_up_question=False,
            strip_meta_framing=True,
        )

        self.assertEqual(result, "1. Что понравилось? 2. Что было некомфортно?")

    def test_detect_crisis_signal_for_self_harm(self):
        crisis = detect_crisis_signal("Я не хочу жить и хочу покончить с собой.")

        self.assertEqual(crisis, "direct_self_harm")

    def test_detect_crisis_signal_for_third_party_mention(self):
        crisis = detect_crisis_signal("Мой друг хочет умереть, я не знаю что делать.")

        self.assertEqual(crisis, "third_party_mention")

    def test_detect_crisis_signal_for_ambiguous_case(self):
        crisis = detect_crisis_signal("Иногда думаю о смерти и хочу просто исчезнуть.")

        self.assertEqual(crisis, "ambiguous_crisis")

    def test_build_crisis_response_mentions_emergency_help(self):
        response = build_crisis_support_response("direct_self_harm")

        self.assertIn("экстренные службы", response.lower())
        self.assertIn("не оставайся один", response.lower())


    def test_human_style_guardrails_soften_hard_rejection_for_risky_scene(self):
        result = apply_human_style_guardrails(
            "Нет. Такой сценарий я тебе расписывать не буду. Под кайфом и без защиты это кончится плохо.",
            answer_first=True,
            allow_follow_up_question=False,
            soften_hard_rejection=True,
        )

        self.assertFalse(result.startswith("Нет"))
        self.assertIn("испортит сцену", result)

    def test_human_style_guardrails_compress_risky_scene_lecture(self):
        result = apply_human_style_guardrails(
            "Нет. Такой сценарий я тебе расписывать не буду. Под кайфом и без защиты это уже не про красивую ночь. "
            "Важно заранее всё обсудить. Сначала договориться о правилах. Потом обозначить стоп. "
            "Никаких резких движений, обязательно защита, никаких наркотиков. "
            "Если вы всё равно собираетесь это делать, максимум музыка и дистанция.",
            answer_first=True,
            allow_follow_up_question=False,
            soften_hard_rejection=True,
            compress_risky_scene_lecture=True,
        )

        self.assertLessEqual(len(result), 400)
        self.assertIn("Так ты это только собьёшь", result)
        self.assertIn("Если хочешь, я", result)
        self.assertNotIn("Важно заранее", result)
        self.assertIn("?", result)

    def test_human_style_guardrails_adds_dialogue_pull_question(self):
        result = apply_human_style_guardrails(
            "Думаю, там слишком легко теряется ясность.",
            answer_first=True,
            allow_follow_up_question=False,
            prefer_follow_up_question=True,
            user_message="Хим секс оргия что ты думаешь",
        )

        self.assertTrue(result.endswith("?"))
        self.assertIn("изменённому состоянию", result)

    def test_human_style_guardrails_support_context_avoids_product_tone(self):
        result = apply_human_style_guardrails(
            "Понимаю.",
            answer_first=True,
            allow_follow_up_question=False,
            prefer_follow_up_question=True,
            user_message="Все цепляет",
        )

        self.assertTrue(result.endswith("?"))
        self.assertIn("горе", result.lower())
        self.assertNotIn("оффер", result.lower())

    def test_human_style_guardrails_compress_charged_probe_lecture(self):
        result = apply_human_style_guardrails(
            "Можно хотеть. Но делать это стоит только трезво и очень ясно. "
            "Если у тебя есть партнёрша, сначала надо всё обсудить. "
            "Потом решить формат, границы, защиту и стоп-слова. "
            "Иначе всё развалится. Если хочешь, могу дать тебе шаблон сообщения.",
            answer_first=False,
            allow_follow_up_question=True,
            compress_charged_probe_lecture=True,
            prefer_follow_up_question=True,
            user_message="Хочу групповой секс",
        )

        self.assertIn("Ок, желание понятно", result)
        self.assertIn("фантазия, разговор с партнёрами или уже реальный план", result)
        self.assertIn("?", result)
        self.assertNotIn("только трезво", result.lower())

    def test_human_style_guardrails_compress_to_dialogue_turn(self):
        result = apply_human_style_guardrails(
            "Это зависит от контекста. Сначала стоит посмотреть на риски, потом взвесить ожидания, потом понять, насколько тебе это вообще подходит. "
            "Иногда лучше не спешить и разобрать всё по шагам. В любом случае решение должно быть осознанным.",
            answer_first=True,
            allow_follow_up_question=True,
            compress_to_dialogue_turn=True,
            prefer_follow_up_question=True,
            user_message="Что думаешь, брать или нет?",
        )

        self.assertLessEqual(len(result), 320)
        self.assertTrue(result.endswith("?"))
        self.assertNotIn("разобрать всё по шагам", result)

    def test_human_style_guardrails_can_skip_topic_follow_up_question(self):
        result = apply_human_style_guardrails(
            "Тут важнее первый сигнал, чем длинная теория.",
            answer_first=True,
            allow_follow_up_question=True,
            prefer_follow_up_question=True,
            topic_questions_enabled=False,
            user_message="Как тебе такой оффер?",
        )

        self.assertFalse(result.endswith("?"))

    def test_comfort_guardrails_strip_abstract_fog_and_question_on_cooldown(self):
        result = apply_human_style_guardrails(
            "Понимаю. Здесь есть скрытые слои внутри тебя, и жизнь как будто стала шире. Что ты чувствуешь?",
            active_mode="comfort",
            answer_first=True,
            allow_follow_up_question=False,
            suppress_follow_up_question=True,
            user_message="Мне тревожно",
        )

        self.assertNotIn("скрытые слои", result.lower())
        self.assertNotIn("жизнь как будто стала шире", result.lower())
        self.assertNotIn("?", result)
        self.assertIn("неочевидные причины", result.lower())

    def test_comfort_guardrails_keep_reply_concise(self):
        result = apply_human_style_guardrails(
            " ".join(
                [
                    "Да, это может сильно выматывать.",
                    "Сейчас важнее не раскопать всю историю, а увидеть ближайший кусок.",
                    "Ты не слабый, ты перегружен.",
                    "Когда человек долго держится, психика начинает экономить силы.",
                    "Поэтому даже простые решения могут казаться неподъёмными.",
                    "Дальше можно было бы долго разбирать детство, отношения и паттерны, но сейчас это только утяжелит ответ.",
                ]
            ),
            active_mode="comfort",
            answer_first=True,
            allow_follow_up_question=False,
        )

        self.assertLessEqual(len(result), 520)
        self.assertLessEqual(result.count(".") + result.count("!") + result.count("?"), 5)


if __name__ == "__main__":
    unittest.main()
