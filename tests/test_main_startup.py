import unittest
from pathlib import Path


class MainStartupTests(unittest.TestCase):
    def test_lifespan_starts_only_single_initiative_worker(self):
        source = Path("main.py").read_text(encoding="utf-8")

        self.assertIn("await container.reengagement_service.start(bot)", source)
        self.assertNotIn("await container.proactive_message_service.start(bot)", source)
        self.assertNotIn("await container.proactive_message_service.close()", source)

    def test_settings_requires_non_default_admin_dashboard_password(self):
        source = Path("config/settings.py").read_text(encoding="utf-8")

        self.assertIn('os.getenv("ADMIN_DASHBOARD_PASSWORD")', source)
        self.assertIn("DEFAULT_ADMIN_DASHBOARD_PASSWORDS", source)
        self.assertIn("non-default strong value", source)

    def test_prelaunch_check_requires_admin_dashboard_password(self):
        source = Path("scripts/prelaunch_check.py").read_text(encoding="utf-8")

        self.assertIn('"ADMIN_DASHBOARD_PASSWORD"', source)
        self.assertIn("_check_admin_dashboard_password", source)
        self.assertIn("non-default strong value", source)

    def test_container_retries_redis_before_fallback(self):
        source = Path("core/container.py").read_text(encoding="utf-8")

        self.assertIn("delays = (0.25, 0.5, 1.0, 2.0, 4.0)", source)
        self.assertIn("time.sleep(delay)", source)
        self.assertIn("using in-memory fallback", source)

    def test_dockerfile_runs_as_non_root_user(self):
        source = Path("Dockerfile").read_text(encoding="utf-8")

        self.assertIn("adduser --system", source)
        self.assertIn("USER app", source)

    def test_systemd_units_run_as_dedicated_user(self):
        bot_service = Path("deploy/systemd/bot.service").read_text(encoding="utf-8")
        dashboard_service = Path("deploy/systemd/admin-dashboard.service").read_text(encoding="utf-8")

        for source in (bot_service, dashboard_service):
            self.assertIn("User=bot", source)
            self.assertIn("Group=bot", source)
            self.assertIn("ProtectSystem=full", source)
            self.assertIn("ReadWritePaths=/opt/bot", source)


if __name__ == "__main__":
    unittest.main()
