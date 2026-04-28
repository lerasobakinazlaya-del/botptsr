import json
import unittest
from pathlib import Path


class RuntimeSettingsRegressionTests(unittest.TestCase):
    def test_public_runtime_copy_is_human_readable(self):
        runtime = json.loads(Path("config/runtime_settings.json").read_text(encoding="utf-8"))
        ui = runtime["ui"]
        payment = runtime["payment"]

        self.assertIn("Быстрый старт", ui["welcome_followup_text"])
        self.assertEqual("💬 Начать диалог", ui["write_button_text"])
        self.assertIn("Мне тревожно", ui["onboarding_prompt_buttons"][0])
        self.assertIn("Premium", payment["buy_cta_text"])
        self.assertNotIn("????", ui["welcome_followup_text"])
        self.assertNotIn("????", payment["premium_benefits_text"])


if __name__ == "__main__":
    unittest.main()
