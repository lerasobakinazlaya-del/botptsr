import unittest
from types import SimpleNamespace

from services.admin_metrics_service import AdminMetricsService


class FakeUserService:
    async def get_total_users(self):
        return 100

    async def get_premium_users_count(self):
        return 12

    async def get_admin_users_count(self):
        return 2

    async def get_new_users_since(self, days: int):
        return {1: 3, 7: 11, 30: 25}[days]

    async def get_daily_registrations(self, days: int = 14):
        return [{"day": "2026-03-29", "users_count": 3}]

    async def get_recent_users(self, limit: int = 20):
        return [{"id": 1, "username": "u", "first_name": "User", "active_mode": "base", "is_premium": False, "is_admin": False, "created_at": "2026-03-29 10:00:00"}]


class FakeMessageRepository:
    async def get_total_messages(self):
        return 500

    async def get_total_users(self):
        return 40


class FakePaymentRepository:
    async def get_overview(self):
        return {"successful_payments": 8, "revenue": 3992.0, "first_payments": 5, "paid_users": 7}

    async def get_successful_payments_since(self, days: int):
        return {1: 1, 7: 4, 30: 8}[days]

    async def get_first_payments_since(self, days: int):
        return {1: 1, 7: 3, 30: 5}[days]

    async def get_daily_payments(self, days: int = 14):
        return [{"day": "2026-03-29", "successful_payments": 2, "revenue": 998.0, "first_payments": 1}]

    async def get_recent_payments(self, limit: int = 20):
        return [{"user_id": 1, "amount": 499.0, "currency": "RUB", "status": "paid", "event_time": "2026-03-29 10:00:00"}]


class FakeMonetizationRepository:
    async def get_funnel_overview(self, days: int = 30):
        if days == 7:
            return {
                "days": 7,
                "stages": {
                    "offer_shown": {"events": 20, "users": 15},
                    "invoice_opened": {"events": 12, "users": 10},
                    "paid": {"events": 4, "users": 4},
                    "renewed": {"events": 1, "users": 1},
                },
                "conversion": {
                    "offer_to_invoice_pct": 66.67,
                    "invoice_to_paid_pct": 40.0,
                    "paid_to_renewed_pct": 25.0,
                },
            }
        return {
            "days": 30,
            "stages": {
                "offer_shown": {"events": 60, "users": 45},
                "invoice_opened": {"events": 30, "users": 24},
                "paid": {"events": 8, "users": 8},
                "renewed": {"events": 2, "users": 2},
            },
            "conversion": {
                "offer_to_invoice_pct": 53.33,
                "invoice_to_paid_pct": 33.33,
                "paid_to_renewed_pct": 25.0,
            },
            }

    async def get_segmented_funnel(self, *, days: int = 30, segment_by: str):
        if segment_by == "offer_trigger":
            return {
                "days": days,
                "segment_by": segment_by,
                "segments": {
                    "limit_reached": {
                        "days": days,
                        "stages": {
                            "offer_shown": {"events": 30, "users": 20},
                            "invoice_opened": {"events": 18, "users": 14},
                            "paid": {"events": 5, "users": 5},
                            "renewed": {"events": 1, "users": 1},
                        },
                        "conversion": {
                            "offer_to_invoice_pct": 70.0,
                            "invoice_to_paid_pct": 35.71,
                            "paid_to_renewed_pct": 20.0,
                        },
                    }
                },
            }
        return {
            "days": days,
            "segment_by": segment_by,
            "segments": {
                "a": {
                    "days": days,
                    "stages": {
                        "offer_shown": {"events": 28, "users": 21},
                        "invoice_opened": {"events": 15, "users": 12},
                        "paid": {"events": 4, "users": 4},
                        "renewed": {"events": 1, "users": 1},
                    },
                    "conversion": {
                        "offer_to_invoice_pct": 57.14,
                        "invoice_to_paid_pct": 33.33,
                        "paid_to_renewed_pct": 25.0,
                    },
                }
            },
        }

    async def get_recent_events(self, limit: int = 20):
        return [{"user_id": 1, "event_name": "offer_shown", "offer_trigger": "limit_reached", "offer_variant": "a", "payment_external_id": None, "created_at": "2026-03-29 10:00:00"}]


class FakeReferralService:
    async def get_overview(self):
        return {"total": 5, "converted": 2, "recent": [{"referred_user_id": 2}]}


class FakeStateRepository:
    async def get_support_stats(self):
        return {"users_with_support_profile": 3, "episode_counts": {"panic": 1}, "self_harm_flags": 0, "last_updated_at": "2026-03-29 10:00:00"}


class FakeProactiveRepository:
    async def get_overview(self):
        return {"sent_1d": 2, "sent_total": 7, "failed_total": 0, "reply_after_proactive_total": 3, "reply_after_proactive_rate": 42.86, "opt_out_after_proactive_total": 1, "opt_out_after_proactive_rate": 14.29, "users_contacted_7d": 4, "recent": [{"user_id": 1}]}


class FakeUserPreferenceRepository:
    async def get_stats(self):
        return {"users_with_timezone": 9, "proactive_disabled_users": 2}


class AdminMetricsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_cached_payload_includes_monetization_funnel(self):
        service = AdminMetricsService(
            user_service=FakeUserService(),
            message_repository=FakeMessageRepository(),
            payment_repository=FakePaymentRepository(),
            monetization_repository=FakeMonetizationRepository(),
            referral_service=FakeReferralService(),
            state_repository=FakeStateRepository(),
            ai_service=SimpleNamespace(get_runtime_stats=lambda: {"queue_size": 0}),
            chat_session_service=SimpleNamespace(get_runtime_stats=lambda: {"active_sessions": 0}),
            proactive_repository=FakeProactiveRepository(),
            user_preference_repository=FakeUserPreferenceRepository(),
            redis=None,
            cache_ttl=0,
        )

        payload = await service._build_cached_payload()

        self.assertEqual(payload["monetization"]["funnel_7d"]["stages"]["offer_shown"]["users"], 15)
        self.assertEqual(payload["monetization"]["funnel_30d"]["conversion"]["invoice_to_paid_pct"], 33.33)
        self.assertEqual(payload["monetization"]["by_trigger_30d"]["segments"]["limit_reached"]["stages"]["paid"]["users"], 5)
        self.assertEqual(payload["monetization"]["by_variant_30d"]["segments"]["a"]["conversion"]["offer_to_invoice_pct"], 57.14)
        self.assertEqual(payload["recent"]["monetization"][0]["event_name"], "offer_shown")
