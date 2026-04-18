import unittest
from types import SimpleNamespace

from handlers.start import start_handler


class FakeMessage:
    def __init__(self, text: str = "/start", user_id: int = 123):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []
        self.photos = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append({"text": text, "reply_markup": reply_markup})

    async def answer_photo(self, photo, caption: str, reply_markup=None):
        self.photos.append({"photo": photo, "caption": caption, "reply_markup": reply_markup})


class FakeUserService:
    def __init__(self, *, is_admin: bool = False, is_new_user: bool = True):
        self._is_admin = is_admin
        self._is_new_user = is_new_user

    async def ensure_user(self, _from_user):
        return self._is_new_user

    async def is_admin(self, _user_id: int):
        return self._is_admin


class FakeAdminSettingsService:
    def __init__(self, avatar_path: str = "", followup_text: str = ""):
        self.avatar_path = avatar_path
        self.followup_text = followup_text

    def get_runtime_settings(self):
        return {
            "ui": {
                "write_button_text": "💬 Начать диалог",
                "modes_button_text": "🧭 Режимы",
                "premium_button_text": "✨ Полный доступ",
                "input_placeholder": "Напиши...",
                "onboarding_input_placeholder": "Выбери вход",
                "onboarding_prompt_buttons": [
                    "Мне тревожно, помоги успокоиться",
                    "Помоги разобрать ситуацию",
                ],
                "start_avatar_path": self.avatar_path,
                "welcome_user_text": "Привет, это тестовое приветствие.",
                "welcome_followup_text": self.followup_text,
                "welcome_admin_text": "Админ-панель активирована.",
            },
            "referral": {
                "start_parameter_prefix": "ref_",
                "referred_welcome_message": "",
            },
        }


class FakeReferralService:
    async def register_referral(self, **_kwargs):
        return False


class FakeStateRepository:
    def __init__(self):
        self.saved = []

    async def get(self, _user_id):
        return {}

    async def save(self, user_id, state, *, commit=True):
        self.saved.append((user_id, state, commit))


class FakeMonetizationRepository:
    def __init__(self):
        self.events = []

    async def log_event(self, **kwargs):
        self.events.append(kwargs)


class StartHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_handler_sends_photo_when_avatar_exists(self):
        message = FakeMessage()

        await start_handler(
            message=message,
            user_service=FakeUserService(),
            admin_settings_service=FakeAdminSettingsService("README.md"),
            referral_service=FakeReferralService(),
        )

        self.assertEqual(len(message.photos), 1)
        self.assertEqual(message.photos[0]["caption"], "Привет, это тестовое приветствие.")
        self.assertEqual(len(message.answers), 0)

    async def test_start_handler_falls_back_to_text_when_avatar_missing(self):
        message = FakeMessage()

        await start_handler(
            message=message,
            user_service=FakeUserService(),
            admin_settings_service=FakeAdminSettingsService("assets/missing-avatar.png"),
            referral_service=FakeReferralService(),
        )

        self.assertEqual(len(message.answers), 1)
        self.assertEqual(message.answers[0]["text"], "Привет, это тестовое приветствие.")
        self.assertEqual(len(message.photos), 0)

    async def test_start_handler_sends_followup_for_new_user_when_configured(self):
        message = FakeMessage()

        await start_handler(
            message=message,
            user_service=FakeUserService(is_new_user=True),
            admin_settings_service=FakeAdminSettingsService(
                avatar_path="assets/missing-avatar.png",
                followup_text="Быстрый старт:\n• Напиши первую задачу",
            ),
            referral_service=FakeReferralService(),
        )

        self.assertEqual(len(message.answers), 2)
        self.assertEqual(message.answers[0]["text"], "Привет, это тестовое приветствие.")
        self.assertEqual(message.answers[1]["text"], "Быстрый старт:\n• Напиши первую задачу")
        self.assertIsNotNone(message.answers[1]["reply_markup"])
        self.assertEqual(len(message.photos), 0)

    async def test_start_handler_tracks_onboarding_state_and_acquisition(self):
        message = FakeMessage(text="/start src_telegram__cmp_spring_launch", user_id=777)
        state_repository = FakeStateRepository()
        monetization_repository = FakeMonetizationRepository()

        await start_handler(
            message=message,
            user_service=FakeUserService(is_new_user=True),
            admin_settings_service=FakeAdminSettingsService(
                avatar_path="assets/missing-avatar.png",
                followup_text="Быстрый старт",
            ),
            referral_service=FakeReferralService(),
            state_repository=state_repository,
            monetization_repository=monetization_repository,
        )

        self.assertEqual(len(state_repository.saved), 1)
        saved_state = state_repository.saved[0][1]
        self.assertEqual(saved_state["acquisition"]["source"], "telegram")
        self.assertEqual(saved_state["acquisition"]["campaign"], "spring_launch")
        self.assertTrue(saved_state["onboarding"]["started_at"])
        self.assertEqual(
            [event["event_name"] for event in monetization_repository.events],
            ["onboarding_started", "acquisition_attributed"],
        )


if __name__ == "__main__":
    unittest.main()
