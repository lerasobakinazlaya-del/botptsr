import unittest

import admin_dashboard


class AdminDashboardTemplateTests(unittest.TestCase):
    def test_runtime_guardrail_phrases_use_escaped_newline_in_script(self):
        html = admin_dashboard._dashboard_html()

        self.assertIn(
            "setValue('#chat_response_guardrail_blocked_phrases',(c.response_guardrail_blocked_phrases||[]).join('\\n'));",
            html,
        )


if __name__ == "__main__":
    unittest.main()
