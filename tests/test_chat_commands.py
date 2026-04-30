import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from handlers.chat import (
    _build_quota_notice,
    _build_subscription_expiry_notice,
    _handle_proactive_command,
    _handle_timezone_command,
    _should_trigger_emotional_paywall,
    _should_trigger_useful_advice_paywall,
)


class FakeUserPreferenceRepository:
    def __init__(self, initial=None):
        self.preferences = initial or {
            "proactive_enabled": True,
            "timezone": None,
            "updated_at": None,
        }

    async def get_preferences(self, user_id: int, *, fallback=None):
        if self.preferences is not None:
            return dict(self.preferences)
        if isinstance(fallback, dict):
            return {
                "proactive_enabled": bool(fallback.get("enabled", True)),
                "timezone": fallback.get("timezone"),
                "updated_at": fallback.get("updated_at"),
            }
        return {
            "proactive_enabled": True,
            "timezone": None,
            "updated_at": None,
        }

    async def set_proactive_enabled(self, user_id: int, enabled: bool):
        self.preferences["proactive_enabled"] = bool(enabled)
        return dict(self.preferences)

    async def set_timezone(self, user_id: int, timezone_name: str | None):
        self.preferences["timezone"] = timezone_name
        return dict(self.preferences)


class FakeStateRepository:
    def __init__(self, initial_state=None):
        self.state = initial_state or {
            "proactive_preferences": {
                "enabled": True,
                "updated_at": None,
                "timezone": None,
            }
        }
        self.saved_states = []

    async def get(self, user_id: int):
        return self.state

    async def save(self, user_id: int, state: dict, *, commit: bool = True):
        self.state = state
        self.saved_states.append((user_id, state, commit))


class FakeMessage:
    def __init__(self, text: str, user_id: int = 123):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text: str):
        self.answers.append(text)


class ChatCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_proactive_off_disables_initiative(self):
        repo = FakeStateRepository()
        pref_repo = FakeUserPreferenceRepository()
        message = FakeMessage("/proactive off")

        handled = await _handle_proactive_command(message, pref_repo, repo)

        self.assertTrue(handled)
        self.assertFalse(repo.state["proactive_preferences"]["enabled"])
        self.assertFalse(pref_repo.preferences["proactive_enabled"])
        self.assertTrue(message.answers)

    async def test_quiet_off_enables_initiative(self):
        repo = FakeStateRepository(
            {
                "proactive_preferences": {
                    "enabled": False,
                    "updated_at": None,
                    "timezone": None,
                }
            }
        )
        pref_repo = FakeUserPreferenceRepository(
            {
                "proactive_enabled": False,
                "timezone": None,
                "updated_at": None,
            }
        )
        message = FakeMessage("/quiet off")

        handled = await _handle_proactive_command(message, pref_repo, repo)

        self.assertTrue(handled)
        self.assertTrue(repo.state["proactive_preferences"]["enabled"])
        self.assertTrue(pref_repo.preferences["proactive_enabled"])
        self.assertTrue(message.answers)

    async def test_timezone_command_sets_timezone(self):
        repo = FakeStateRepository()
        pref_repo = FakeUserPreferenceRepository()
        message = FakeMessage("/timezone Europe/Moscow")

        handled = await _handle_timezone_command(message, pref_repo, repo)

        self.assertTrue(handled)
        self.assertEqual(repo.state["proactive_preferences"]["timezone"], "Europe/Moscow")
        self.assertEqual(pref_repo.preferences["timezone"], "Europe/Moscow")
        self.assertIn("Europe/Moscow", message.answers[-1])

    async def test_timezone_command_resets_timezone(self):
        repo = FakeStateRepository(
            {
                "proactive_preferences": {
                    "enabled": True,
                    "updated_at": None,
                    "timezone": "Europe/Moscow",
                }
            }
        )
        pref_repo = FakeUserPreferenceRepository(
            {
                "proactive_enabled": True,
                "timezone": "Europe/Moscow",
                "updated_at": None,
            }
        )
        message = FakeMessage("/timezone reset")

        handled = await _handle_timezone_command(message, pref_repo, repo)

        self.assertTrue(handled)
        self.assertIsNone(repo.state["proactive_preferences"]["timezone"])
        self.assertIsNone(pref_repo.preferences["timezone"])
        self.assertTrue(message.answers)

    def test_quota_notice_warns_when_free_messages_are_low(self):
        state, notice = _build_quota_notice(
            {},
            {"is_premium": False},
            11,
            {
                "free_daily_messages_enabled": True,
                "free_daily_messages_limit": 12,
                "free_daily_warning_thresholds": [5, 3, 1],
                "free_daily_warning_template": "Осталось {remaining} из {limit}",
            },
        )

        self.assertIn("Осталось 1 из 12", notice)
        repeated_state, repeated_notice = _build_quota_notice(
            state,
            {"is_premium": False},
            11,
            {
                "free_daily_messages_enabled": True,
                "free_daily_messages_limit": 12,
                "free_daily_warning_thresholds": [5, 3, 1],
                "free_daily_warning_template": "Осталось {remaining} из {limit}",
            },
        )
        self.assertIsNone(repeated_notice)
        self.assertEqual(state, repeated_state)

    def test_subscription_expiry_notice_warns_once_per_day(self):
        far_from_expiry = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        near_expiry = (datetime.now(timezone.utc) + timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        payment_service = SimpleNamespace(
            get_payment_settings=lambda: {
                "renewal_reminder_days": [7, 3, 1],
                "expiry_reminder_template": "Подписка закончится через {days} дн.",
            },
            format_expiry_text=lambda _: "01.04.2026 12:00 UTC",
        )

        state, notice = _build_subscription_expiry_notice(
            {},
            {
                "is_premium": True,
                "premium_expires_at": far_from_expiry,
            },
            payment_service,
        )

        self.assertIsNone(notice)
        state, notice = _build_subscription_expiry_notice(
            {},
            {
                "is_premium": True,
                "premium_expires_at": near_expiry,
            },
            payment_service,
        )
        self.assertIn("Подписка закончится через 1 дн.", notice)
        repeated_state, repeated_notice = _build_subscription_expiry_notice(
            state,
            {
                "is_premium": True,
                "premium_expires_at": near_expiry,
            },
            payment_service,
        )
        self.assertIsNone(repeated_notice)
        self.assertEqual(state, repeated_state)

    def test_soft_paywall_suppressed_for_sensitive_emotional_context(self):
        triggered = _should_trigger_emotional_paywall(
            user={"subscription_plan": "free"},
            state={"interaction_count": 8, "emotional_tone": "anxious"},
            user_text="Мне паника и боль в груди",
            response="x" * 180,
        )

        self.assertFalse(triggered)

    def test_useful_paywall_suppressed_for_medical_context(self):
        triggered = _should_trigger_useful_advice_paywall(
            user={"subscription_plan": "free"},
            active_mode="mentor",
            user_text="Помоги, аритмия и что делать",
            response="1. шаг\n2. план",
        )

        self.assertFalse(triggered)
