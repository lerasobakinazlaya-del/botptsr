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
        self.assertEqual("day_pass", payment["default_package_key"])
        self.assertIn("day_pass", payment["packages"])
        self.assertIn("pro_month", payment["packages"])
        self.assertIn("premium_month", payment["packages"])
        self.assertNotIn("day", payment["packages"])
        self.assertNotIn("week", payment["packages"])
        self.assertTrue(runtime["limits"]["free_long_task_enabled"])
        self.assertIn("offer_long_task_template", payment)
        self.assertNotIn("????", payment["offer_emotional_engagement_template"])
        self.assertNotIn("????", payment["offer_useful_advice_template"])
        self.assertIn("Premium", payment["premium_menu_description_template"])

    def test_user_facing_config_has_no_mojibake_markers(self):
        markers = ("Рџ", "Рњ", "Р§", "СЏ", "вЂ", "рџ")
        paths = (
            Path("config/runtime_settings.json"),
            Path("config/prompt_templates.json"),
            Path("config/mode_catalog.json"),
        )

        offenders = []
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            found = [marker for marker in markers if marker in text]
            if found:
                offenders.append(f"{path}: {', '.join(found)}")

        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
