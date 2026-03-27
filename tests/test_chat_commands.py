import unittest
from types import SimpleNamespace

from handlers.chat import _handle_proactive_command, _handle_timezone_command


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
