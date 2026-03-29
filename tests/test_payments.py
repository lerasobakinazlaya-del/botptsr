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
        self.offer_events = []
        self.invoice_events = []

    def get_payment_settings(self):
        return {
            "currency": "RUB",
            "price_minor_units": 49900,
            "access_duration_days": 30,
            "premium_benefits_text": "Преимущества Premium",
            "buy_cta_text": "Купить Premium",
            "offer_cta_text_a": "Открыть Premium на 30 дней",
            "offer_cta_text_b": "Снять лимиты и открыть все режимы",
            "offer_benefits_text_a": "120 сообщений в день, все режимы и приоритетный доступ без обрыва диалога.",
            "offer_benefits_text_b": "Premium открывает закрытые режимы, повышенный лимит и более стабильный доступ каждый день.",
            "offer_price_line_template": "Сейчас: {price_label} за {access_days} дней.",
            "offer_limit_reached_template": "Бесплатный лимит на сегодня закончился. Premium даст {premium_limit} сообщений в день и доступ ко всем режимам на {access_days} дней.",
            "offer_locked_mode_template": "Режим {mode_name} доступен только в Premium. Открой все закрытые режимы и лимит до {premium_limit} сообщений в день на {access_days} дней.",
            "unavailable_message": "Оплата сейчас недоступна",
            "invoice_error_message": "Не удалось создать счёт",
        }

    def is_enabled(self) -> bool:
        return self.enabled

    def get_offer_variant(self, user_id: int) -> str:
        return "a" if user_id % 2 == 0 else "b"

    def build_subscription_status_text(self, user):
        if user and user.get("is_premium"):
            return "Premium активен до 01.04.2026"
        return ""

    async def track_offer_shown(self, **kwargs):
        self.offer_events.append(kwargs)

    async def track_invoice_opened(self, **kwargs):
        self.invoice_events.append(kwargs)

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
        self.is_first_payment = True

    async def save_payment(self, **kwargs):
        self.saved = kwargs
        return {
            "is_first_payment": self.is_first_payment,
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
                "product_title": "Подписка Premium",
                "product_description": "Открой премиум-режимы.",
                "premium_benefits_text": "Преимущества Premium",
                "buy_cta_text": "Купить Premium",
                "recurring_button_text": "Открыть оплату",
                "already_premium_message": "Premium уже активен.",
                "unavailable_message": "Оплата сейчас недоступна",
                "invoice_error_message": "Не удалось создать счёт",
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


class FakeMonetizationRepository:
    def __init__(self):
        self.events = []
        self.latest_offer_context = {
            "offer_trigger": "limit_reached",
            "offer_variant": "b",
        }

    async def log_event(self, **kwargs):
        self.events.append(kwargs)

    async def get_latest_offer_context(self, user_id: int):
        return dict(self.latest_offer_context)


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
        self.assertEqual(payment_service.offer_events[0]["variant"], "b")
        self.assertEqual(payment_service.invoice_events[0]["variant"], "b")
        self.assertEqual(
            message.answers[0]["text"],
            "Premium активен до 01.04.2026\n\nСнять лимиты и открыть все режимы\n\nСейчас: 499.00 RUB за 30 дней.\n\nPremium открывает закрытые режимы, повышенный лимит и более стабильный доступ каждый день.",
        )

    async def test_send_premium_offer_sends_intro_and_invoice(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer()

        result = await send_premium_offer(message, payment_service, user_service)

        self.assertTrue(result)
        self.assertEqual(payment_service.invoice_calls, 1)
        self.assertEqual(payment_service.offer_events[0]["trigger"], "default")
        self.assertEqual(payment_service.invoice_events[0]["trigger"], "default")
        self.assertEqual(
            message.answers[0]["text"],
            "Снять лимиты и открыть все режимы\n\nСейчас: 499.00 RUB за 30 дней.\n\nPremium открывает закрытые режимы, повышенный лимит и более стабильный доступ каждый день.",
        )

    async def test_send_premium_offer_uses_alternate_ab_variant_for_even_user(self):
        message = FakeMessage(user_id=124)
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer({"id": 124, "is_premium": False, "premium_expires_at": None})

        result = await send_premium_offer(message, payment_service, user_service)

        self.assertTrue(result)
        self.assertEqual(payment_service.offer_events[0]["variant"], "a")
        self.assertEqual(
            message.answers[0]["text"],
            "Открыть Premium на 30 дней\n\nСейчас: 499.00 RUB за 30 дней.\n\n120 сообщений в день, все режимы и приоритетный доступ без обрыва диалога.",
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
        self.assertEqual(payment_service.offer_events[0]["trigger"], OFFER_TRIGGER_LIMIT_REACHED)
        self.assertEqual(
            message.answers[0]["text"],
            "Бесплатный лимит на сегодня закончился. Premium даст 120 сообщений в день и доступ ко всем режимам на 30 дней.\n\nСнять лимиты и открыть все режимы\n\nСейчас: 499.00 RUB за 30 дней.\n\nPremium открывает закрытые режимы, повышенный лимит и более стабильный доступ каждый день.",
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
        self.assertEqual(payment_service.offer_events[0]["trigger"], OFFER_TRIGGER_MODE_LOCKED)
        self.assertEqual(
            message.answers[0]["text"],
            "Режим Mentor доступен только в Premium. Открой все закрытые режимы и лимит до 120 сообщений в день на 30 дней.\n\nСнять лимиты и открыть все режимы\n\nСейчас: 499.00 RUB за 30 дней.\n\nPremium открывает закрытые режимы, повышенный лимит и более стабильный доступ каждый день.",
        )

    async def test_handle_successful_payment_saves_payment_and_grants_subscription_days(self):
        payment_repository = FakePaymentRepository()
        user_service = FakeUserService()
        referral_service = FakeReferralService()
        monetization_repository = FakeMonetizationRepository()
        service = PaymentService(
            settings=SimpleNamespace(
                payment_provider_token="",
                payment_currency="RUB",
                premium_price_minor_units=49900,
                premium_product_title="Подписка Premium",
                premium_product_description="Открой премиум-режимы.",
            ),
            payment_repository=payment_repository,
            user_service=user_service,
            settings_service=FakeSettingsService(),
            referral_service=referral_service,
            monetization_repository=monetization_repository,
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
        self.assertEqual(
            monetization_repository.events[-1]["event_name"],
            "paid",
        )
        self.assertEqual(
            monetization_repository.events[-1]["offer_trigger"],
            "limit_reached",
        )
        self.assertEqual(
            monetization_repository.events[-1]["offer_variant"],
            "b",
        )

    async def test_handle_successful_payment_uses_provider_subscription_expiry_when_present(self):
        subscription_expires_at = datetime(2026, 3, 31, 4, 0, 0, tzinfo=timezone.utc)
        payment_repository = FakePaymentRepository()
        payment_repository.is_first_payment = False
        user_service = FakeUserService()
        monetization_repository = FakeMonetizationRepository()
        service = PaymentService(
            settings=SimpleNamespace(
                payment_provider_token="",
                payment_currency="XTR",
                premium_price_minor_units=349,
                premium_product_title="Подписка Premium",
                premium_product_description="Открой премиум-режимы.",
            ),
            payment_repository=payment_repository,
            user_service=user_service,
            settings_service=FakeSettingsService(),
            referral_service=FakeReferralService(),
            monetization_repository=monetization_repository,
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
        self.assertEqual(
            monetization_repository.events[-1]["event_name"],
            "renewed",
        )
        self.assertEqual(
            monetization_repository.events[-1]["offer_variant"],
            "b",
        )


class PaymentFormattingTests(unittest.TestCase):
    def test_build_success_message_includes_expiry(self):
        service = PaymentService(
            settings=SimpleNamespace(
                payment_provider_token="",
                payment_currency="RUB",
                premium_price_minor_units=49900,
                premium_product_title="Подписка Premium",
                premium_product_description="Открой премиум-режимы.",
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

    def test_modes_keyboard_marks_all_premium_modes_explicitly(self):
        keyboard = get_modes_keyboard(
            {"is_premium": False},
            {
                "ui": {"premium_button_text": "Premium"},
                "limits": {
                    "mode_preview_enabled": True,
                    "mode_daily_limits": {"passion": 2},
                },
            },
            {
                "base": {
                    "key": "base",
                    "name": "Базовый",
                    "icon": "💬",
                    "is_premium": False,
                    "sort_order": 10,
                },
                "passion": {
                    "key": "passion",
                    "name": "Близость",
                    "icon": "🔥",
                    "is_premium": True,
                    "sort_order": 20,
                },
                "mentor": {
                    "key": "mentor",
                    "name": "Наставник",
                    "icon": "🧠",
                    "is_premium": True,
                    "sort_order": 30,
                },
            },
        )

        texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("🔥 Близость • Премиум (2/день)", texts)
        self.assertIn("🧠 Наставник • Премиум", texts)
