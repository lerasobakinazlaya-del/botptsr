import unittest

from handlers.modes import build_mode_saved_text, build_modes_menu_text


class ModesMenuTests(unittest.TestCase):
    def test_free_user_modes_menu_contains_premium_bridge(self):
        text = build_modes_menu_text(
            {"is_premium": False},
            {"ui": {"modes_title": "Выбери режим общения:", "premium_button_text": "✨ Полный доступ"}},
            {
                "base": {"name": "База", "is_premium": False},
                "comfort": {"name": "Психолог", "is_premium": True},
            },
        )

        self.assertIn("✨ Полный доступ", text)
        self.assertIn("Психолог", text)
        self.assertIn("более глубокие ответы", text)

    def test_premium_user_modes_menu_does_not_upsell(self):
        text = build_modes_menu_text(
            {"is_premium": True},
            {"ui": {"modes_title": "Выбери режим общения:", "premium_button_text": "✨ Полный доступ"}},
            {"comfort": {"name": "Психолог", "is_premium": True}},
        )

        self.assertNotIn("Полный доступ", text)


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
