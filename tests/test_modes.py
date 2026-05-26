import unittest

from handlers.modes import build_mode_saved_text, build_modes_menu_text


class ModesMenuTests(unittest.TestCase):
    def test_free_user_modes_menu_stays_clean(self):
        text = build_modes_menu_text(
            {"is_premium": False},
            {"ui": {"modes_title": "Выбери режим общения:", "premium_button_text": "✨ Планы"}},
            {
                "base": {"name": "База", "is_premium": False},
                "comfort": {"name": "Психолог", "is_premium": True},
            },
        )

        self.assertEqual("Выбери режим общения:", text)

    def test_premium_user_modes_menu_does_not_upsell(self):
        text = build_modes_menu_text(
            {"is_premium": True},
            {"ui": {"modes_title": "Выбери режим общения:", "premium_button_text": "✨ Планы"}},
            {"comfort": {"name": "Психолог", "is_premium": True}},
        )

        self.assertNotIn("Планы", text)

    def test_modes_menu_shows_product_descriptions_when_available(self):
        text = build_modes_menu_text(
            {"is_premium": False},
            {"ui": {"modes_title": "Выбери режим общения:"}},
            {
                "mentor": {
                    "name": "Разбор",
                    "icon": "🧠",
                    "description": "Для задач и решений: отделить главное от шума.",
                    "sort_order": 30,
                },
                "base": {
                    "name": "Диалог",
                    "icon": "💬",
                    "description": "Для обычного разговора без консультационного формата.",
                    "sort_order": 10,
                },
            },
        )

        self.assertIn("💬 Диалог — Для обычного разговора", text)
        self.assertIn("🧠 Разбор — Для задач и решений", text)
        self.assertLess(text.index("Диалог"), text.index("Разбор"))

    def test_preview_mode_saved_text_explains_remaining_trial(self):
        text = build_mode_saved_text(
            mode_name="Разбор",
            activation_phrase="Собираем суть.",
            ui_settings={"mode_saved_template": "Режим: {mode_name}\n\n{activation_phrase}"},
            access_status={"is_preview": True, "remaining": 2, "daily_limit": 2},
        )

        self.assertIn("Пробный доступ", text)
        self.assertIn("осталось 2 из 2", text)
        self.assertIn("Pro/Premium", text)


if __name__ == "__main__":
    unittest.main()
