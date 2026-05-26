import unittest

from services.product_entitlements_service import ProductEntitlementsService


class ProductEntitlementsServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ProductEntitlementsService()
        self.runtime_settings = {
            "ai": {
                "openai_model": "gpt-4o-mini",
                "temperature": 0.9,
                "max_completion_tokens": 420,
                "memory_max_tokens": 1500,
                "history_message_limit": 20,
                "plan_overrides": {
                    "free": {
                        "model": "gpt-4o-mini",
                        "max_completion_tokens": 180,
                        "memory_max_tokens": 700,
                        "history_message_limit": 12,
                    },
                    "pro": {
                        "model": "gpt-5.4-mini",
                        "max_completion_tokens": 320,
                        "memory_max_tokens": 1200,
                        "history_message_limit": 18,
                    },
                    "premium": {
                        "model": "gpt-5.4",
                        "max_completion_tokens": 520,
                        "memory_max_tokens": 1800,
                        "history_message_limit": 24,
                    },
                },
                "mode_overrides": {
                    "mentor": {
                        "temperature": 0.5,
                        "prompt_suffix": "mentor",
                    }
                },
            },
            "limits": {
                "free_daily_messages_enabled": True,
                "free_daily_messages_limit": 5,
                "free_daily_warning_thresholds": [3],
                "free_daily_warning_template": "left {remaining}",
                "free_daily_limit_message": "free done",
                "pro_daily_messages_enabled": True,
                "pro_daily_messages_limit": 80,
                "premium_daily_messages_enabled": True,
                "premium_daily_messages_limit": 200,
                "mode_preview_enabled": True,
                "mode_preview_default_limit": 2,
                "mode_daily_limits": {"mentor": 1},
            },
        }
        self.mode_catalog = {
            "base": {"is_premium": False},
            "comfort": {"is_premium": True},
            "mentor": {"is_premium": True},
            "deep": {"min_plan": "premium"},
        }

    def test_daily_limit_comes_from_single_plan_contract(self):
        free = self.service.get_plan_daily_limit(
            plan_key="free",
            limits_settings=self.runtime_settings["limits"],
        )
        pro = self.service.get_plan_daily_limit(
            plan_key="pro",
            limits_settings=self.runtime_settings["limits"],
        )
        premium = self.service.get_plan_daily_limit(
            plan_key="premium",
            limits_settings=self.runtime_settings["limits"],
        )

        self.assertEqual(5, free["limit"])
        self.assertEqual([3], free["warning_thresholds"])
        self.assertEqual(80, pro["limit"])
        self.assertEqual(200, premium["limit"])

    def test_mode_access_supports_legacy_paid_modes_and_min_plan(self):
        free_user = {"subscription_plan": "free", "is_premium": False}
        pro_user = {"subscription_plan": "pro", "is_premium": True}
        premium_user = {"subscription_plan": "premium", "is_premium": True}

        free_comfort = self.service.get_mode_access_status(
            user=free_user,
            mode_key="comfort",
            state={},
            runtime_settings=self.runtime_settings,
            mode_catalog=self.mode_catalog,
        )
        self.assertTrue(free_comfort["allowed"])
        self.assertTrue(free_comfort["is_preview"])
        self.assertEqual(2, free_comfort["daily_limit"])
        self.assertEqual("pro", free_comfort["min_plan"])

        pro_comfort = self.service.get_mode_access_status(
            user=pro_user,
            mode_key="comfort",
            state={},
            runtime_settings=self.runtime_settings,
            mode_catalog=self.mode_catalog,
        )
        self.assertTrue(pro_comfort["allowed"])
        self.assertFalse(pro_comfort["is_preview"])

        premium_deep = self.service.get_mode_access_status(
            user=premium_user,
            mode_key="deep",
            state={},
            runtime_settings=self.runtime_settings,
            mode_catalog=self.mode_catalog,
        )
        self.assertTrue(premium_deep["allowed"])
        self.assertFalse(premium_deep["is_preview"])

    def test_preview_usage_is_registered_only_for_preview_modes(self):
        free_user = {"subscription_plan": "free", "is_premium": False}
        state = self.service.register_successful_mode_message(
            {},
            user=free_user,
            mode_key="mentor",
            runtime_settings=self.runtime_settings,
            mode_catalog=self.mode_catalog,
        )

        status = self.service.get_mode_access_status(
            user=free_user,
            mode_key="mentor",
            state=state,
            runtime_settings=self.runtime_settings,
            mode_catalog=self.mode_catalog,
        )

        self.assertFalse(status["allowed"])
        self.assertEqual(0, status["remaining"])

    def test_ai_profile_routes_by_plan_inside_product_contract(self):
        pro_profile = self.service.get_ai_profile(
            runtime_settings=self.runtime_settings,
            active_mode="mentor",
            user={"subscription_plan": "pro"},
        )
        premium_profile = self.service.get_ai_profile(
            runtime_settings=self.runtime_settings,
            active_mode="mentor",
            user={"subscription_plan": "premium"},
        )

        self.assertEqual("gpt-5.4-mini", pro_profile["model"])
        self.assertEqual("gpt-5.4", premium_profile["model"])
        self.assertEqual(0.5, pro_profile["temperature"])
        self.assertIn("mentor", pro_profile["prompt_suffix"])

    def test_snapshot_gives_handlers_one_product_view(self):
        snapshot = self.service.build_snapshot(
            user={"subscription_plan": "free"},
            runtime_settings=self.runtime_settings,
            mode_catalog=self.mode_catalog,
            active_mode="comfort",
            state={},
            today_messages=2,
            monthly_messages=10,
            monthly_chat_tokens=1000,
        )

        self.assertEqual("free", snapshot["plan"])
        self.assertEqual(3, snapshot["daily_messages"]["remaining"])
        self.assertTrue(snapshot["mode_access"]["is_preview"])
        self.assertEqual(10, snapshot["monthly_messages"]["used"])
        self.assertEqual(1000, snapshot["monthly_chat_tokens"]["used"])


if __name__ == "__main__":
    unittest.main()
