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

    def test_modes_page_exposes_per_mode_gpt_model_and_saves_it(self):
        source = Path("admin_dashboard.py").read_text(encoding="utf-8")

        self.assertIn('data-mode-model="${k}"', source)
        self.assertIn("modeModels[mode]={model:String(i.value||'').trim()}", source)
        self.assertIn("await api('/api/settings/runtime',{method:'PUT',body:JSON.stringify({ai:{mode_overrides:p.modeModels}})})", source)

    def test_runtime_page_uses_single_initiative_settings_block(self):
        source = Path("admin_dashboard.py").read_text(encoding="utf-8")

        self.assertIn("initiative_enabled", source)
        self.assertIn("initiative_idle_hours", source)
        self.assertIn("initiative_timezone", source)
        self.assertIn("engagement:{reengagement_enabled:$('#initiative_enabled').checked", source)
        self.assertNotIn("engagement_reengagement_enabled", source)

    def test_state_summary_formats_memory_objects_instead_of_object_object(self):
        source = Path("admin_dashboard.py").read_text(encoding="utf-8")

        self.assertIn("function formatStateObject(value)", source)
        self.assertIn("renderStateSection('Контекст памяти',memoryOverview)", source)
        self.assertIn("renderStateSection('Сводка эпизода',Object.entries(episodicSummary))", source)


if __name__ == "__main__":
    unittest.main()
