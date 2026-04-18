import unittest

from services.referral_service import ReferralService


class FakeCursor:
    def __init__(self, row):
        self.row = row

    async def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self):
        self.referrals = {
            200: {
                "referrer_user_id": 100,
                "referred_user_id": 200,
                "status": "pending",
                "reward_amount_minor_units": 0,
                "external_payment_id": "",
            }
        }

    async def execute(self, query, params=()):
        normalized = " ".join(query.split()).lower()
        if normalized.startswith("select referrer_user_id, status from referrals"):
            referred_user_id = params[0]
            row = self.referrals.get(referred_user_id)
            return FakeCursor((row["referrer_user_id"], row["status"]) if row else None)
        if normalized.startswith("select referrer_user_id, reward_amount_minor_units, external_payment_id, status from referrals"):
            referred_user_id = params[0]
            row = self.referrals.get(referred_user_id)
            if row is None:
                return FakeCursor(None)
            return FakeCursor(
                (
                    row["referrer_user_id"],
                    row["reward_amount_minor_units"],
                    row["external_payment_id"],
                    row["status"],
                )
            )
        if normalized.startswith("update referrals set status = 'converted'"):
            amount_minor_units, external_payment_id, referred_user_id = params
            row = self.referrals[referred_user_id]
            row["status"] = "converted"
            row["reward_amount_minor_units"] = amount_minor_units
            row["external_payment_id"] = external_payment_id
            return FakeCursor(None)
        if normalized.startswith("update referrals set status = 'rewarded'"):
            referred_user_id = params[0]
            row = self.referrals[referred_user_id]
            row["status"] = "rewarded"
            return FakeCursor(None)
        raise AssertionError(f"Unexpected query: {query}")

    async def commit(self):
        return None


class FakeDB:
    def __init__(self):
        self.connection = FakeConnection()


class FakeUserService:
    def __init__(self):
        self.subscription_grants = []

    async def user_exists(self, _user_id):
        return True

    async def grant_subscription_days(self, user_id, plan_key, days):
        self.subscription_grants.append((user_id, plan_key, days))
        return "2026-05-01 10:00:00"


class FakeSettingsService:
    def get_runtime_settings(self):
        return {
            "referral": {
                "enabled": True,
                "allow_self_referral": False,
                "start_parameter_prefix": "ref_",
                "require_first_paid_invoice": True,
                "require_activation_before_reward": True,
                "award_referrer_premium": True,
                "award_referred_user_premium": False,
                "reward_premium_days": 7,
                "reward_plan_key": "pro",
            }
        }


class FakeStateRepository:
    def __init__(self):
        self.activated = False

    async def get(self, _user_id):
        return {
            "onboarding": {
                "activation_reached_at": "2026-04-18T12:00:00+00:00" if self.activated else None,
            }
        }


class ReferralServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_payment_waits_for_activation_before_reward(self):
        user_service = FakeUserService()
        state_repository = FakeStateRepository()
        service = ReferralService(
            db=FakeDB(),
            user_service=user_service,
            settings_service=FakeSettingsService(),
            state_repository=state_repository,
        )

        result = await service.process_successful_payment(
            referred_user_id=200,
            amount_minor_units=44900,
            external_payment_id="pay_1",
            is_first_payment=True,
        )

        self.assertIsNotNone(result)
        self.assertFalse(result["reward_granted"])
        self.assertEqual(user_service.subscription_grants, [])

    async def test_activation_grants_reward_after_successful_payment(self):
        user_service = FakeUserService()
        state_repository = FakeStateRepository()
        service = ReferralService(
            db=FakeDB(),
            user_service=user_service,
            settings_service=FakeSettingsService(),
            state_repository=state_repository,
        )

        await service.process_successful_payment(
            referred_user_id=200,
            amount_minor_units=44900,
            external_payment_id="pay_1",
            is_first_payment=True,
        )
        state_repository.activated = True

        result = await service.process_activation(200)

        self.assertIsNotNone(result)
        self.assertTrue(result["reward_granted"])
        self.assertEqual(user_service.subscription_grants, [(100, "pro", 7)])


if __name__ == "__main__":
    unittest.main()
