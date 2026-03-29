import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from handlers.payments import (
    CALLBACK_BUY_PREMIUM,
    OFFER_TRIGGER_LIMIT_REACHED,
    OFFER_TRIGGER_MODE_LOCKED,
    send_premium_offer,
)
from keyboards.modes_keyboard import get_modes_keyboard
from services.payment_service import PaymentService


class FakeMessage:
    def __init__(self, user_id: int = 123):
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append({"text": text, "reply_markup": reply_markup})


class FakePaymentServiceForOffer:
    def __init__(self, *, enabled: bool = True, invoice_result: bool = True):
        self.enabled = enabled
        self.invoice_result = invoice_result
        self.invoice_calls = 0

    def get_payment_settings(self):
        return {
            "currency": "RUB",
            "price_minor_units": 49900,
            "access_duration_days": 30,
            "premium_benefits_text": "Premium benefits",
            "buy_cta_text": "Buy premium",
            "offer_cta_text_a": "Open Premium for 30 days",
            "offer_cta_text_b": "Remove limits and unlock all modes",
            "offer_benefits_text_a": "120 messages per day and all modes.",
            "offer_benefits_text_b": "Premium unlocks paid modes and a higher daily limit.",
            "offer_price_line_template": "Now: {price_label} for {access_days} days.",
            "offer_limit_reached_template": "Free quota is over. Premium gives {premium_limit} messages per day for {access_days} days.",
            "offer_locked_mode_template": "{mode_name} is available in Premium. Unlock all paid modes and up to {premium_limit} messages per day for {access_days} days.",
            "unavailable_message": "Payments unavailable",
            "invoice_error_message": "Invoice failed",
        }

    def is_enabled(self) -> bool:
        return self.enabled

    def build_subscription_status_text(self, user):
        if user and user.get("is_premium"):
            return "Premium active until 01.04.2026"
        return ""

    async def send_premium_invoice(self, message):
        self.invoice_calls += 1
        return self.invoice_result


class FakeUserServiceForOffer:
    def __init__(self, user: dict | None = None):
        self.user = user or {
            "id": 123,
            "is_premium": False,
            "premium_expires_at": None,
        }

    async def get_user(self, user_id: int):
        return dict(self.user)


class FakePaymentRepository:
    def __init__(self):
        self.saved = None

    async def save_payment(self, **kwargs):
        self.saved = kwargs
        return {
            "is_first_payment": True,
            "paid_at": "2026-03-29 12:00:00",
        }


class FakeUserService:
    def __init__(self):
        self.grants = []
        self.set_until_calls = []

    async def grant_premium_days(self, user_id: int, days: int) -> str:
        self.grants.append((user_id, days))
        return "2026-04-28 12:00:00"

    async def set_premium_until(self, user_id: int, expires_at) -> bool:
        self.set_until_calls.append((user_id, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
        return True


class FakeSettingsService:
    def get_runtime_settings(self):
        return {
            "payment": {
                "provider_token": "provider-token",
                "currency": "RUB",
                "price_minor_units": 49900,
                "access_duration_days": 30,
                "recurring_stars_enabled": True,
                "product_title": "Premium access",
                "product_description": "Unlock premium chat modes.",
                "premium_benefits_text": "Premium benefits",
                "buy_cta_text": "Buy premium",
                "recurring_button_text": "Open payment",
                "already_premium_message": "Premium active.",
                "unavailable_message": "Payments unavailable",
                "invoice_error_message": "Invoice failed",
                "success_message": "Payment success",
                "renewal_reminder_days": [7, 3, 1],
                "expiry_reminder_template": "Expires in {days} days",
            }
        }


class FakeReferralService:
    def __init__(self):
        self.calls = []

    async def process_successful_payment(self, **kwargs):
        self.calls.append(kwargs)
        return {"referrer_user_id": 77}


class PaymentFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_premium_offer_allows_renewal_for_active_user(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer(
            {
                "id": 123,
                "is_premium": True,
                "premium_expires_at": "2026-04-01 12:00:00",
            }
        )

        result = await send_premium_offer(message, payment_service, user_service)

        self.assertTrue(result)
        self.assertEqual(payment_service.invoice_calls, 1)
        self.assertEqual(
            message.answers[0]["text"],
            "Premium active until 01.04.2026\n\nRemove limits and unlock all modes\n\nNow: 499.00 RUB for 30 days.\n\nPremium unlocks paid modes and a higher daily limit.",
        )

    async def test_send_premium_offer_sends_intro_and_invoice(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer()

        result = await send_premium_offer(message, payment_service, user_service)

        self.assertTrue(result)
        self.assertEqual(payment_service.invoice_calls, 1)
        self.assertEqual(
            message.answers[0]["text"],
            "Remove limits and unlock all modes\n\nNow: 499.00 RUB for 30 days.\n\nPremium unlocks paid modes and a higher daily limit.",
        )

    async def test_send_premium_offer_uses_alternate_ab_variant_for_even_user(self):
        message = FakeMessage(user_id=124)
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer({"id": 124, "is_premium": False, "premium_expires_at": None})

        result = await send_premium_offer(message, payment_service, user_service)

        self.assertTrue(result)
        self.assertEqual(
            message.answers[0]["text"],
            "Open Premium for 30 days\n\nNow: 499.00 RUB for 30 days.\n\n120 messages per day and all modes.",
        )

    async def test_send_premium_offer_uses_limit_reached_pitch(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer()

        result = await send_premium_offer(
            message,
            payment_service,
            user_service,
            trigger=OFFER_TRIGGER_LIMIT_REACHED,
            premium_limit=120,
        )

        self.assertTrue(result)
        self.assertEqual(
            message.answers[0]["text"],
            "Free quota is over. Premium gives 120 messages per day for 30 days.\n\nRemove limits and unlock all modes\n\nNow: 499.00 RUB for 30 days.\n\nPremium unlocks paid modes and a higher daily limit.",
        )

    async def test_send_premium_offer_uses_mode_locked_pitch(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer()

        result = await send_premium_offer(
            message,
            payment_service,
            user_service,
            trigger=OFFER_TRIGGER_MODE_LOCKED,
            mode_name="Mentor",
            premium_limit=120,
        )

        self.assertTrue(result)
        self.assertEqual(
            message.answers[0]["text"],
            "Mentor is available in Premium. Unlock all paid modes and up to 120 messages per day for 30 days.\n\nRemove limits and unlock all modes\n\nNow: 499.00 RUB for 30 days.\n\nPremium unlocks paid modes and a higher daily limit.",
        )

    async def test_handle_successful_payment_saves_payment_and_grants_subscription_days(self):
        payment_repository = FakePaymentRepository()
        user_service = FakeUserService()
        referral_service = FakeReferralService()
        service = PaymentService(
            settings=SimpleNamespace(
                payment_provider_token="",
                payment_currency="RUB",
                premium_price_minor_units=49900,
                premium_product_title="Premium access",
                premium_product_description="Unlock premium chat modes.",
            ),
            payment_repository=payment_repository,
            user_service=user_service,
            settings_service=FakeSettingsService(),
            referral_service=referral_service,
        )
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            successful_payment=SimpleNamespace(
                invoice_payload="premium:42",
                total_amount=49900,
                currency="RUB",
                telegram_payment_charge_id="tg-charge-1",
                provider_payment_charge_id="provider-charge-1",
                subscription_expiration_date=None,
                is_recurring=False,
                is_first_recurring=False,
            ),
        )

        result = await service.handle_successful_payment(message)

        self.assertEqual(user_service.grants, [(42, 30)])
        self.assertEqual(user_service.set_until_calls, [])
        self.assertIsNotNone(payment_repository.saved)
        self.assertEqual(payment_repository.saved["amount"], 499.0)
        self.assertEqual(payment_repository.saved["status"], "paid")
        self.assertEqual(payment_repository.saved["external_payment_id"], "tg-charge-1")
        self.assertEqual(payment_repository.saved["metadata"]["premium_expires_at"], "2026-04-28 12:00:00")
        self.assertEqual(
            referral_service.calls,
            [
                {
                    "referred_user_id": 42,
                    "amount_minor_units": 49900,
                    "external_payment_id": "tg-charge-1",
                    "is_first_payment": True,
                }
            ],
        )
        self.assertEqual(result["premium_expires_at"], "2026-04-28 12:00:00")
        self.assertEqual(result["referral"]["referrer_user_id"], 77)

    async def test_handle_successful_payment_uses_provider_subscription_expiry_when_present(self):
        subscription_expires_at = datetime(2026, 3, 31, 4, 0, 0, tzinfo=timezone.utc)
        payment_repository = FakePaymentRepository()
        user_service = FakeUserService()
        service = PaymentService(
            settings=SimpleNamespace(
                payment_provider_token="",
                payment_currency="XTR",
                premium_price_minor_units=349,
                premium_product_title="Premium access",
                premium_product_description="Unlock premium chat modes.",
            ),
            payment_repository=payment_repository,
            user_service=user_service,
            settings_service=FakeSettingsService(),
            referral_service=FakeReferralService(),
        )
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            successful_payment=SimpleNamespace(
                invoice_payload="premium:42",
                total_amount=349,
                currency="XTR",
                telegram_payment_charge_id="tg-charge-2",
                provider_payment_charge_id="provider-charge-2",
                subscription_expiration_date=int(subscription_expires_at.timestamp()),
                is_recurring=True,
                is_first_recurring=True,
            ),
        )

        result = await service.handle_successful_payment(message)

        self.assertEqual(user_service.grants, [])
        self.assertEqual(
            user_service.set_until_calls,
            [(42, subscription_expires_at.strftime("%Y-%m-%d %H:%M:%S"))],
        )
        self.assertTrue(result["is_recurring"])


class PaymentFormattingTests(unittest.TestCase):
    def test_build_success_message_includes_expiry(self):
        service = PaymentService(
            settings=SimpleNamespace(
                payment_provider_token="",
                payment_currency="RUB",
                premium_price_minor_units=49900,
                premium_product_title="Premium access",
                premium_product_description="Unlock premium chat modes.",
            ),
            payment_repository=FakePaymentRepository(),
            user_service=FakeUserService(),
            settings_service=FakeSettingsService(),
            referral_service=FakeReferralService(),
        )

        text = service.build_success_message(
            {
                "premium_expires_at": "2026-04-28 12:00:00",
                "is_recurring": False,
            }
        )

        self.assertIn("Payment success", text)
        self.assertIn("28.04.2026 12:00 UTC", text)


class ModesKeyboardTests(unittest.TestCase):
    def test_modes_keyboard_adds_buy_button_for_non_premium_user(self):
        keyboard = get_modes_keyboard(
            {"is_premium": False},
            {"ui": {"premium_button_text": "Premium"}, "limits": {}},
        )

        self.assertEqual(keyboard.inline_keyboard[-1][0].callback_data, CALLBACK_BUY_PREMIUM)
        self.assertEqual(keyboard.inline_keyboard[-1][0].text, "Premium")

    def test_modes_keyboard_hides_buy_button_for_premium_user(self):
        keyboard = get_modes_keyboard(
            {"is_premium": True},
            {"ui": {"premium_button_text": "Premium"}, "limits": {}},
        )

        callback_data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        self.assertNotIn(CALLBACK_BUY_PREMIUM, callback_data)
