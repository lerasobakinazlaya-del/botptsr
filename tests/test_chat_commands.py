import unittest
from types import SimpleNamespace

from handlers.chat import _handle_proactive_command, _handle_timezone_command


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
        message = FakeMessage("/proactive off")

        handled = await _handle_proactive_command(message, repo)

        self.assertTrue(handled)
        self.assertFalse(repo.state["proactive_preferences"]["enabled"])
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
        message = FakeMessage("/quiet off")

        handled = await _handle_proactive_command(message, repo)

        self.assertTrue(handled)
        self.assertTrue(repo.state["proactive_preferences"]["enabled"])
        self.assertTrue(message.answers)

    async def test_timezone_command_sets_timezone(self):
        repo = FakeStateRepository()
        message = FakeMessage("/timezone Europe/Moscow")

        handled = await _handle_timezone_command(message, repo)

        self.assertTrue(handled)
        self.assertEqual(
            repo.state["proactive_preferences"]["timezone"],
            "Europe/Moscow",
        )
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
        message = FakeMessage("/timezone reset")

        handled = await _handle_timezone_command(message, repo)

        self.assertTrue(handled)
        self.assertIsNone(repo.state["proactive_preferences"]["timezone"])
        self.assertTrue(message.answers)
