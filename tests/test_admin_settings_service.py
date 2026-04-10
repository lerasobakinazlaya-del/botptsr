import tempfile
import unittest
from pathlib import Path

from services.admin_settings_service import AdminSettingsService


class AdminSettingsServiceModeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings = AdminSettingsService(base_dir=Path(self.temp_dir.name))

    def test_legacy_comfort_mode_override_migrates_to_ptsd(self):
        runtime = self.settings.update_runtime_settings(
            {
                "ai": {
                    "mode_overrides": {
                        "comfort": {
                            "temperature": 0.61,
                            "prompt_suffix": "legacy comfort override",
                        }
                    }
                }
            }
        )

        self.assertIn("ptsd", runtime["ai"]["mode_overrides"])
        self.assertNotIn("comfort", runtime["ai"]["mode_overrides"])
        self.assertEqual(runtime["ai"]["mode_overrides"]["ptsd"]["temperature"], 0.61)

    def test_legacy_comfort_mode_catalog_migrates_to_ptsd(self):
        catalog = self.settings.update_mode_catalog(
            {
                "comfort": {
                    "name": "Legacy comfort",
                    "description": "legacy",
                }
            }
        )

        self.assertIn("ptsd", catalog)
        self.assertNotIn("comfort", catalog)
        self.assertEqual(catalog["ptsd"]["name"], "Legacy comfort")

    def test_legacy_comfort_mode_scales_migrates_to_ptsd(self):
        modes = self.settings.update_modes(
            {
                "comfort": {
                    "warmth": 7,
                    "structure": 4,
                }
            }
        )

        self.assertIn("ptsd", modes)
        self.assertNotIn("comfort", modes)
        self.assertEqual(modes["ptsd"]["warmth"], 7)
        self.assertEqual(modes["ptsd"]["structure"], 4)


if __name__ == "__main__":
    unittest.main()
