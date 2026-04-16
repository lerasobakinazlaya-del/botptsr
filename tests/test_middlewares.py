import unittest

from core.middlewares import ThrottlingMiddleware


class FakeSettingsService:
    def get_runtime_settings(self):
        return {
            "safety": {
                "throttle_rate_limit_seconds": 1.5,
                "throttle_warning_interval_seconds": 5.0,
                "throttle_warning_text": "Слишком много сообщений подряд. Подожди немного.",
            },
            "ui": {
                "write_button_text": "💬 Начать диалог",
                "modes_button_text": "🧭 Режимы",
                "premium_button_text": "✨ Premium",
            },
        }


class ThrottlingMiddlewareTests(unittest.TestCase):
    def test_ui_buttons_are_exempt_from_throttle(self):
        middleware = ThrottlingMiddleware(redis=None, settings_service=FakeSettingsService())

        self.assertTrue(middleware._is_throttle_exempt_text("💬 Начать диалог"))
        self.assertTrue(middleware._is_throttle_exempt_text("🧭 Режимы"))
        self.assertTrue(middleware._is_throttle_exempt_text("✨ Premium"))

    def test_regular_user_text_is_not_exempt_from_throttle(self):
        middleware = ThrottlingMiddleware(redis=None, settings_service=FakeSettingsService())

        self.assertFalse(middleware._is_throttle_exempt_text("Мне тревожно"))
        self.assertFalse(middleware._is_throttle_exempt_text("/start"))
        self.assertFalse(middleware._is_throttle_exempt_text(""))


if __name__ == "__main__":
    unittest.main()
