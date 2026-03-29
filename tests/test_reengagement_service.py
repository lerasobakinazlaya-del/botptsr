import unittest
from datetime import datetime as real_datetime
from types import SimpleNamespace

from services.reengagement_service import ReengagementService


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, user_id, text):
        self.messages.append((user_id, text))


class FakeAIService:
    def __init__(self, result=None):
        self.result = result or SimpleNamespace(
            response="**Привет**",
            new_state={"active_mode": "base"},
        )
        self.calls = []
        self.human_memory_service = SimpleNamespace(
            can_send_reengagement=lambda *args, **kwargs: True,
            get_reengagement_context=lambda state: {"topic": "", "callback_hint": ""},
        )

    async def generate_reengagement(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeMessageRepository:
    async def get_last_messages(self, **kwargs):
        return []

    async def save(self, *args, **kwargs):
        return None


class FakeStateRepository:
    def __init__(self, state):
        self.state = state
        self.saved = []

    async def get(self, user_id):
        return dict(self.state)

    async def save(self, user_id, state, *, commit=True):
        self.saved.append((user_id, state, commit))


class FakeUserPreferenceRepository:
    def __init__(self, preferences):
        self.preferences = preferences

    async def get_preferences(self, user_id, *, fallback=None):
        return dict(self.preferences)


class FakeUserService:
    def __init__(self, user=None):
        self.user = user or {"is_admin": False}

    async def get_user(self, user_id):
        return dict(self.user)


class FakeSettingsService:
    def __init__(self, *, quiet_hours_enabled=False):
        self.runtime_settings = {
            "engagement": {
                "reengagement_min_hours_between": 24,
                "reengagement_poll_seconds": 60,
                "reengagement_enabled": True,
                "reengagement_idle_hours": 24,
                "reengagement_recent_window_days": 14,
                "reengagement_batch_size": 10,
            },
            "proactive": {
                "quiet_hours_enabled": quiet_hours_enabled,
                "quiet_hours_start": 0,
                "quiet_hours_end": 8,
                "timezone": "Europe/Moscow",
            },
            "ai": {
                "history_message_limit": 20,
            },
        }
        self.modes = {
            "base": {
                "allow_bold": False,
                "allow_italic": False,
            }
        }

    def get_runtime_settings(self):
        return self.runtime_settings

    def get_modes(self):
        return self.modes


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeDB:
    def transaction(self):
        return FakeTransaction()


class FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return real_datetime(2026, 1, 1, 2, 0, 0)
        return real_datetime(2026, 1, 1, 2, 0, 0, tzinfo=tz)


class ReengagementServiceTests(unittest.IsolatedAsyncioTestCase):
    def _build_service(self, *, preferences=None, result=None, quiet_hours_enabled=False):
        service = ReengagementService(
            ai_service=FakeAIService(result=result),
            message_repository=FakeMessageRepository(),
            state_repository=FakeStateRepository({"active_mode": "base", "relationship_state": {}}),
            user_preference_repository=FakeUserPreferenceRepository(
                preferences
                or {
                    "proactive_enabled": True,
                    "timezone": None,
                    "updated_at": None,
                }
            ),
            user_service=FakeUserService(),
            settings_service=FakeSettingsService(quiet_hours_enabled=quiet_hours_enabled),
            db=FakeDB(),
        )
        service._bot = FakeBot()
        return service

    async def test_process_candidate_skips_when_user_opted_out(self):
        service = self._build_service(
            preferences={
                "proactive_enabled": False,
                "timezone": None,
                "updated_at": None,
            }
        )

        await service._process_candidate(
            {"user_id": 1, "last_user_message_at": "2026-01-01 00:00:00"},
            service.settings_service.get_runtime_settings()["engagement"],
        )

        self.assertEqual(service.ai_service.calls, [])
        self.assertEqual(service._bot.messages, [])

    async def test_process_candidate_formats_reengagement_message(self):
        service = self._build_service(
            result=SimpleNamespace(
                response="**Привет**",
                new_state={"active_mode": "base"},
            )
        )

        await service._process_candidate(
            {"user_id": 1, "last_user_message_at": "2026-01-01 00:00:00"},
            service.settings_service.get_runtime_settings()["engagement"],
        )

        self.assertEqual(len(service.ai_service.calls), 1)
        self.assertEqual(service._bot.messages, [(1, "Привет")])

    async def test_process_candidate_skips_when_last_message_is_not_assistant(self):
        service = self._build_service()

        await service._process_candidate(
            {
                "user_id": 1,
                "last_user_message_at": "2026-01-01 00:00:00",
                "last_message_role": "user",
            },
            service.settings_service.get_runtime_settings()["engagement"],
        )

        self.assertEqual(service.ai_service.calls, [])
        self.assertEqual(service._bot.messages, [])

    def test_quiet_hours_respects_timezone(self):
        service = self._build_service(quiet_hours_enabled=True)
        settings = service.settings_service.get_runtime_settings()["proactive"]

        from unittest.mock import patch

        with patch("services.reengagement_service.datetime", FixedDateTime):
            self.assertTrue(
                service._is_in_quiet_hours(settings, timezone_name="Europe/Moscow")
            )

    async def test_process_candidate_skips_when_last_mood_is_heavy(self):
        service = self._build_service()
        service.state_repository = FakeStateRepository(
            {
                "active_mode": "base",
                "relationship_state": {
                    "last_user_mood": "тревога или внутреннее напряжение",
                },
            }
        )

        await service._process_candidate(
            {"user_id": 1, "last_user_message_at": "2026-01-01 00:00:00"},
            service.settings_service.get_runtime_settings()["engagement"],
        )

        self.assertEqual(service.ai_service.calls, [])
        self.assertEqual(service._bot.messages, [])

    async def test_process_candidate_skips_when_emotional_tone_is_heavy(self):
        service = self._build_service()
        service.state_repository = FakeStateRepository(
            {
                "active_mode": "base",
                "emotional_tone": "anxious",
                "relationship_state": {},
            }
        )

        await service._process_candidate(
            {"user_id": 1, "last_user_message_at": "2026-01-01 00:00:00"},
            service.settings_service.get_runtime_settings()["engagement"],
        )

        self.assertEqual(service.ai_service.calls, [])
        self.assertEqual(service._bot.messages, [])
