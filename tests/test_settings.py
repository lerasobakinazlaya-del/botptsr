import os
import unittest
from unittest.mock import patch

from config.settings import get_settings


class SettingsTests(unittest.TestCase):
    def test_openai_worker_settings_have_safe_minimums(self):
        env = {
            "BOT_TOKEN": "token",
            "OPENAI_API_KEY": "key",
            "OWNER_ID": "1",
            "ADMIN_ID": "1",
            "ADMIN_DASHBOARD_PASSWORD": "strong-password",
            "OPENAI_MAX_PARALLEL_REQUESTS": "0",
            "OPENAI_QUEUE_SIZE": "0",
            "OPENAI_QUEUE_WAIT_TIMEOUT_SECONDS": "0",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = get_settings()

        self.assertEqual(1, settings.openai_max_parallel_requests)
        self.assertEqual(1, settings.openai_queue_size)
        self.assertEqual(1, settings.openai_queue_wait_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
