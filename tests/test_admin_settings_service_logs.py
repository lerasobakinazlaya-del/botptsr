import tempfile
import unittest
from pathlib import Path

from services.admin_settings_service import AdminSettingsService


class AdminSettingsServiceLogTests(unittest.TestCase):
    def test_get_logs_returns_bounded_tail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AdminSettingsService(base_dir=temp_dir)
            log_path = Path(temp_dir) / "logs" / "bot.log"
            log_path.write_text(
                "\n".join(f"line-{index}" for index in range(200)),
                encoding="utf-8",
            )

            payload = service.get_logs(lines=5)

        self.assertTrue(payload["exists"])
        self.assertEqual(
            ["line-195", "line-196", "line-197", "line-198", "line-199"],
            payload["lines"],
        )


if __name__ == "__main__":
    unittest.main()
