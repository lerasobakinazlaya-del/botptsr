import re
import unittest
from pathlib import Path


class AdminDashboardTemplateTests(unittest.TestCase):
    def _admin_source(self) -> str:
        return Path("admin_dashboard.py").read_text(encoding="utf-8")

    def test_runtime_guardrail_phrases_use_escaped_newline_in_script(self):
        source = self._admin_source()

        self.assertIn(
            "setValue('#chat_response_guardrail_blocked_phrases',(c.response_guardrail_blocked_phrases||[]).join('\\\\n'));",
            source,
        )

    def test_admin_test_prompt_uses_conversation_engine_v2(self):
        source = self._admin_source()

        self.assertIn("container.ai_service.conversation_engine.build_system_prompt(", source)
        self.assertIn("ConversationEngineV2", source)

    def test_modes_page_exposes_per_mode_gpt_model_and_saves_it(self):
        source = self._admin_source()

        self.assertIn('data-mode-model="${k}"', source)
        self.assertIn("modeModels[mode]={model:String(i.value||'').trim()}", source)
        self.assertIn("await api('/api/settings/runtime',{method:'PUT',body:JSON.stringify({ai:{mode_overrides:p.modeModels}})})", source)

    def test_runtime_page_uses_single_initiative_settings_block(self):
        source = self._admin_source()

        self.assertIn("initiative_enabled", source)
        self.assertIn("initiative_idle_hours", source)
        self.assertIn("initiative_timezone", source)
        self.assertIn("initiative_style_allow_question", source)
        self.assertIn("initiative_style_max_chars", source)
        self.assertIn("initiative_family_callback_thread", source)
        self.assertIn("engagement:{reengagement_enabled:$('#initiative_enabled').checked", source)
        self.assertIn("reengagement_style:{enabled_families:collectInitiativeFamilies()", source)
        self.assertNotIn("engagement_reengagement_enabled", source)

    def test_runtime_page_exposes_dialogue_and_fast_lane_controls(self):
        source = self._admin_source()

        self.assertIn('id="preset_dialogue_live"', source)
        self.assertIn('id="dialogue_hook_max_sentences"', source)
        self.assertIn('id="dialogue_hook_max_chars"', source)
        self.assertIn('id="fast_lane_enabled"', source)
        self.assertIn('id="fast_lane_hook_max_completion_tokens"', source)
        self.assertIn('id="fast_lane_generic_timeout_seconds"', source)
        self.assertIn('id="ui_start_avatar_path"', source)
        self.assertIn("function applyDialoguePreset(name)", source)
        self.assertIn("function applyInitiativePreset(name)", source)

    def test_testing_page_can_preview_reengagement(self):
        source = self._admin_source()

        self.assertIn('id="test_user_id"', source)
        self.assertIn('id="test-reengagement"', source)
        self.assertIn("/api/test/reengagement", source)

    def test_state_summary_formats_memory_objects_instead_of_object_object(self):
        source = self._admin_source()

        self.assertIn("function formatStateObject(value)", source)
        self.assertIn("renderStateSection('Контекст памяти',memoryOverview)", source)
        self.assertIn("renderStateSection('Сводка эпизода',Object.entries(episodicSummary))", source)

    def test_dashboard_shell_has_product_header_and_sidebar_context(self):
        source = self._admin_source()

        self.assertIn('id="header-title"', source)
        self.assertIn('id="header-subtitle"', source)
        self.assertIn('id="header-release"', source)
        self.assertIn('id="header-sync"', source)
        self.assertIn('id="header-context"', source)
        self.assertIn('id="sidebar-meta"', source)
        self.assertIn("function renderChrome()", source)

    def test_dashboard_exposes_saas_setup_and_conversation_lab(self):
        source = self._admin_source()

        self.assertIn('data-view="setup"', source)
        self.assertIn('id="setup-readiness"', source)
        self.assertIn('id="overview-launch-readiness"', source)
        self.assertIn("function launchReadinessItems()", source)
        self.assertIn("function renderSetup()", source)
        self.assertIn("Conversation Lab", source)
        self.assertIn('id="test-quality"', source)
        self.assertIn("function renderTestQuality()", source)
        self.assertIn("data-test-case", source)

    def test_payments_page_is_reframed_as_plans(self):
        source = self._admin_source()

        self.assertIn("Plans и оплата", source)
        self.assertIn("Пакеты Plans", source)
        self.assertIn("Тарифы конечного пользователя", source)

    def test_static_id_selectors_used_by_js_exist_in_markup(self):
        source = self._admin_source()
        html_ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', source))
        selector_ids = set(re.findall(r"on\('#([A-Za-z0-9_-]+)'", source))
        selector_ids.update(
            selector
            for selector in re.findall(r"\$\('#([^']+)'\)", source)
            if re.fullmatch(r"[A-Za-z0-9_-]+", selector)
        )
        selector_ids.update(
            selector
            for selector in re.findall(r"set(?:Value|Checked)\('#([^']+)'", source)
            if re.fullmatch(r"[A-Za-z0-9_-]+", selector)
        )

        missing = sorted(selector_ids - html_ids)
        self.assertEqual([], missing, f"В админке есть селекторы без элементов: {missing}")


if __name__ == "__main__":
    unittest.main()
