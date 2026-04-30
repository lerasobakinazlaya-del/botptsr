import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from services.admin_settings_service import AdminSettingsService


class AdminSettingsServiceCacheTests(unittest.TestCase):
    def test_bot_process_sees_runtime_model_change_even_if_mtime_is_restored(self):
        with TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            bot_settings = AdminSettingsService(base_dir=base_dir)
            admin_settings = AdminSettingsService(base_dir=base_dir)

            before = bot_settings.get_runtime_settings()
            self.assertTrue(before["ai"]["openai_model"])

            runtime_path = base_dir / "config" / "runtime_settings.json"
            stat_before = runtime_path.stat()

            admin_settings.update_runtime_settings({"ai": {"openai_model": "gpt-test-model"}})

            # Simulate a file system where mtime resolution is too coarse (or unchanged).
            # Restore mtime to the old value; a mtime-only cache would miss the update forever.
            os.utime(
                runtime_path,
                ns=(int(stat_before.st_atime_ns), int(stat_before.st_mtime_ns)),
            )

            after = bot_settings.get_runtime_settings()
            self.assertEqual(after["ai"]["openai_model"], "gpt-test-model")

    def test_legacy_payment_packages_are_migrated_to_product_keys(self):
        with TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            settings = AdminSettingsService(base_dir=base_dir)

            settings.update_runtime_settings(
                {
                    "payment": {
                        "default_package_key": "month",
                        "packages": {
                            "month": {
                                "enabled": True,
                                "title": "Legacy month",
                                "description": "Legacy monthly plan",
                                "price_minor_units": 55500,
                                "access_duration_days": 30,
                                "sort_order": 30,
                                "badge": "Legacy",
                                "recurring_stars_enabled": True,
                            }
                        },
                    }
                }
            )

            runtime = settings.get_runtime_settings()
            payment = runtime["payment"]

            self.assertEqual("premium_month", payment["default_package_key"])
            self.assertIn("pro_month", payment["packages"])
            self.assertIn("premium_month", payment["packages"])
            self.assertNotIn("month", payment["packages"])


if __name__ == "__main__":
    unittest.main()
