import unittest
from datetime import datetime as real_datetime
from unittest.mock import patch

from services.proactive_message_service import ProactiveMessageService


class FakeUserService:
    def __init__(self, user):
        self.user = user

    async def get_user(self, user_id: int):
        return self.user


class FakeStateRepository:
    def __init__(self, state):
        self.state = state

    async def get(self, user_id: int):
        return self.state


class FakeUserPreferenceRepository:
    def __init__(self, preferences=None):
        self.preferences = preferences or {
            "proactive_enabled": True,
            "timezone": None,
            "updated_at": None,
        }

    async def get_preferences(self, user_id: int, *, fallback=None):
        return dict(self.preferences)


class FakeProactiveRepository:
    def __init__(self, silence=False, recent=False):
        self.silence = silence
        self.recent = recent

    async def has_event_for_silence(self, **kwargs):
        return self.silence

    async def has_recent_event(self, **kwargs):
        return self.recent


class FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return real_datetime(2026, 1, 1, 2, 0, 0)
        return real_datetime(2026, 1, 1, 2, 0, 0, tzinfo=tz)


class ProactiveMessageServiceTests(unittest.IsolatedAsyncioTestCase):
    def _build_service(self, state, *, user=None, silence=False, recent=False):
        return ProactiveMessageService(
            client=None,
            message_repository=None,
            proactive_repository=FakeProactiveRepository(silence=silence, recent=recent),
            user_preference_repository=FakeUserPreferenceRepository(
                {
                    "proactive_enabled": bool(
                        (state.get("proactive_preferences") or {}).get("enabled", True)
                    ),
                    "timezone": (state.get("proactive_preferences") or {}).get("timezone"),
                    "updated_at": None,
                }
            ),
            state_repository=FakeStateRepository(state),
            long_term_memory_service=None,
            keyword_memory_service=None,
            prompt_builder=None,
            access_engine=None,
            settings_service=None,
            user_service=FakeUserService(user or {"is_admin": False}),
        )

    async def test_is_eligible_false_when_user_opted_out(self):
        service = self._build_service(
            {
                "interaction_count": 12,
                "interest": 0.8,
                "irritation": 0.1,
                "fatigue": 0.1,
                "emotional_tone": "warm",
                "proactive_preferences": {
                    "enabled": False,
                    "timezone": None,
                },
            }
        )
        candidate = {
            "user_id": 1,
            "last_message_role": "assistant",
            "last_user_message_at": "2026-01-01 00:00:00",
        }
        settings = {
            "cooldown_hours": 72,
            "min_interaction_count": 6,
            "min_interest": 0.45,
            "max_irritation": 0.35,
            "max_fatigue": 0.65,
            "quiet_hours_enabled": False,
        }

        eligible = await service._is_eligible(candidate, settings)

        self.assertFalse(eligible)

    async def test_is_eligible_true_for_healthy_state(self):
        service = self._build_service(
            {
                "interaction_count": 12,
                "interest": 0.8,
                "irritation": 0.1,
                "fatigue": 0.1,
                "emotional_tone": "warm",
                "proactive_preferences": {
                    "enabled": True,
                    "timezone": None,
                },
            }
        )
        candidate = {
            "user_id": 1,
            "last_message_role": "assistant",
            "last_user_message_at": "2026-01-01 00:00:00",
        }
        settings = {
            "cooldown_hours": 72,
            "min_interaction_count": 6,
            "min_interest": 0.45,
            "max_irritation": 0.35,
            "max_fatigue": 0.65,
            "quiet_hours_enabled": False,
        }

        eligible = await service._is_eligible(candidate, settings)

        self.assertTrue(eligible)
        self.assertIn("state_snapshot", candidate)

    def test_quiet_hours_respects_timezone_window(self):
        service = self._build_service({})
        settings = {
            "quiet_hours_enabled": True,
            "quiet_hours_start": 0,
            "quiet_hours_end": 8,
            "timezone": "Europe/Moscow",
        }

        with patch("services.proactive_message_service.datetime", FixedDateTime):
            self.assertTrue(
                service._is_in_quiet_hours(settings, timezone_name="Europe/Moscow")
            )
