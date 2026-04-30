import json
import unittest
from pathlib import Path


class RuntimeSettingsRegressionTests(unittest.TestCase):
    def test_public_runtime_copy_is_human_readable(self):
        runtime = json.loads(Path("config/runtime_settings.json").read_text(encoding="utf-8"))
        ui = runtime["ui"]
        payment = runtime["payment"]
        engagement = runtime["engagement"]

        self.assertIn("Быстрый старт", ui["welcome_followup_text"])
        self.assertEqual("💬 Начать диалог", ui["write_button_text"])
        self.assertIn("Мне тревожно", ui["onboarding_prompt_buttons"][0])
        self.assertIn("Premium", payment["buy_cta_text"])
        self.assertNotIn("????", ui["welcome_followup_text"])
        self.assertNotIn("????", payment["premium_benefits_text"])
        self.assertTrue(engagement["reengagement_enabled"])
        self.assertEqual(12, engagement["reengagement_idle_hours"])
        self.assertTrue(runtime["cost_control"]["usage_alerts"]["enabled"])
        self.assertGreater(runtime["cost_control"]["usage_alerts"]["daily_tokens_warn"], 0)
        self.assertEqual("pro_month", payment["default_package_key"])
        self.assertIn("pro_month", payment["packages"])
        self.assertIn("premium_month", payment["packages"])
        self.assertNotIn("day", payment["packages"])
        self.assertNotIn("week", payment["packages"])
        self.assertNotIn("????", payment["offer_emotional_engagement_template"])
        self.assertNotIn("????", payment["offer_useful_advice_template"])
        self.assertIn("Premium", payment["premium_menu_description_template"])


if __name__ == "__main__":
    unittest.main()
