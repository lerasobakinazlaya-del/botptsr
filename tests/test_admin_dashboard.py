import unittest
from pathlib import Path


class AdminDashboardTemplateTests(unittest.TestCase):
    def test_runtime_guardrail_phrases_use_escaped_newline_in_script(self):
        source = Path("admin_dashboard.py").read_text(encoding="utf-8")

        self.assertIn(
            "setValue('#chat_response_guardrail_blocked_phrases',(c.response_guardrail_blocked_phrases||[]).join('\\\\n'));",
            source,
        )

    def test_admin_test_prompt_uses_conversation_engine_v2(self):
        source = Path("admin_dashboard.py").read_text(encoding="utf-8")

        self.assertIn("container.ai_service.conversation_engine.build_system_prompt(", source)
        self.assertIn("ConversationEngineV2", source)


if __name__ == "__main__":
    unittest.main()
