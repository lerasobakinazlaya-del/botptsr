import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from handlers.modes import build_modes_menu_text
from handlers.payments import (
    CALLBACK_BUY_PREMIUM,
    CALLBACK_CONFIRM_VIRTUAL_PAYMENT,
    CALLBACK_OPEN_PREMIUM_MENU,
    OFFER_TRIGGER_LIMIT_REACHED,
    OFFER_TRIGGER_MODE_LOCKED,
    OFFER_TRIGGER_PREVIEW_EXHAUSTED,
    send_premium_offer,
    show_premium_menu,
)
from keyboards.modes_keyboard import get_modes_keyboard
from services.mode_access_service import ModeAccessService
from services.payment_service import PaymentService


def build_test_packages():
    return {
        "pro_month": {
            "key": "pro_month",
            "enabled": True,
            "title": "Pro на 30 дней",
            "description": "Базовый платный план: больше сообщений, все режимы и память.",
            "price_minor_units": 44900,
            "access_duration_days": 30,
            "sort_order": 10,
            "badge": "Старт",
            "recurring_stars_enabled": True,
            "plan_key": "pro",
        },
        "pro_year": {
            "key": "pro_year",
            "enabled": True,
            "title": "Pro на 365 дней",
            "description": "Годовой доступ к плану Pro.",
            "price_minor_units": 399000,
            "access_duration_days": 365,
            "sort_order": 20,
            "badge": "Выгодно",
            "recurring_stars_enabled": False,
            "plan_key": "pro",
        },
        "premium_month": {
            "key": "premium_month",
            "enabled": True,
            "title": "Premium на 30 дней",
            "description": "Глубокие разборы и длинные ответы.",
            "price_minor_units": 99000,
            "access_duration_days": 30,
            "sort_order": 30,
            "badge": "Глубже",
            "recurring_stars_enabled": True,
            "plan_key": "premium",
        },
        "premium_year": {
            "key": "premium_year",
            "enabled": True,
            "title": "Premium на 365 дней",
            "description": "Годовой доступ к плану Premium.",
            "price_minor_units": 899000,
            "access_duration_days": 365,
            "sort_order": 40,
            "badge": "Выгодно",
            "recurring_stars_enabled": False,
            "plan_key": "premium",
        },
    }


class FakeMessage:
    def __init__(self, user_id: int = 123):
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []
        self.edits = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append({"text": text, "reply_markup": reply_markup})

    async def edit_text(self, text: str, reply_markup=None):
        self.edits.append({"text": text, "reply_markup": reply_markup})


class FakePaymentServiceForOffer:
    def __init__(self, *, enabled: bool = True, invoice_result: bool = True, virtual_mode: bool = False):
        self.enabled = enabled
        self.invoice_result = invoice_result
        self.virtual_mode = virtual_mode
        self.invoice_calls = 0
        self.invoice_package_keys = []
        self.offer_events = []
        self.invoice_events = []
        self.virtual_payment_calls = []

    def get_payment_settings(self):
        return {
            "mode": "virtual" if self.virtual_mode else "telegram",
            "currency": "RUB",
            "default_package_key": "pro_month",
            "price_minor_units": 44900,
            "access_duration_days": 30,
            "packages": build_test_packages(),
            "premium_benefits_text": "Преимущества платного тарифа",
            "buy_cta_text": "Открыть тариф",
            "offer_cta_text_a": "Открыть Pro",
            "offer_cta_text_b": "Снять лимиты и открыть все режимы",
            "offer_benefits_text_a": "80 сообщений в день, все режимы и память.",
            "offer_benefits_text_b": "Premium дает более длинные ответы и глубокие разборы.",
            "offer_price_line_template": "Сейчас: {price_label} за {access_days} дней.",
            "offer_limit_reached_template": "Бесплатный лимит закончился. Платный тариф даст продолжение без паузы.",
            "offer_locked_mode_template": "Режим {mode_name} доступен на платных тарифах. Лимит Premium: {premium_limit} сообщений в день.",
            "offer_preview_exhausted_template": "Пробный доступ к режиму {mode_name} на сегодня закончился. Платный тариф вернет доступ.",
            "premium_menu_description_template": "Платные тарифы открывают: {premium_modes_list}. Цена: {price_label} на {access_days_label}. Лимит Premium: {premium_daily_limit}.",
            "premium_menu_packages_title": "Выбери пакет:",
            "premium_menu_package_line_template": "• {title} — {price_label} на {access_days_label}",
            "premium_menu_package_button_template": "{title} • {price_label}",
            "premium_menu_preview_template": "Пробно: {preview_modes_list}.",
            "premium_menu_back_button_text": "← К режимам",
            "virtual_payment_description_template": "Тестовая оплата\n\nТариф: {package_title}\nЦена: {price_label}\nСрок: {access_days_label}",
            "virtual_payment_button_template": "Подтвердить тестовую оплату • {price_label}",
            "virtual_payment_completed_message": "Тестовая оплата подтверждена.",
            "unavailable_message": "Оплата сейчас недоступна",
            "invoice_error_message": "Не удалось создать счет",
            "product_description": "Открой платный тариф.",
            "success_message": "Payment success",
        }

    def is_enabled(self) -> bool:
        return self.enabled

    def get_offer_variant(self, user_id: int) -> str:
        return "a" if user_id % 2 == 0 else "b"

    def build_subscription_status_text(self, user):
        if user and user.get("is_premium"):
            return "Premium активен до 01.04.2026"
        return ""

    def uses_virtual_payments(self, payment_settings=None):
        return self.virtual_mode

    def get_enabled_packages(self, payment_settings=None):
        payment = payment_settings or self.get_payment_settings()
        return sorted(
            [dict(item) for item in payment["packages"].values() if item.get("enabled")],
            key=lambda item: item.get("sort_order", 0),
        )

    def get_default_package_key(self, payment_settings=None):
        payment = payment_settings or self.get_payment_settings()
        return payment.get("default_package_key", "pro_month")

    def get_default_package(self, payment_settings=None):
        return self.get_package(self.get_default_package_key(payment_settings), payment_settings)

    def get_package(self, package_key=None, payment_settings=None):
        payment = payment_settings or self.get_payment_settings()
        key = package_key or self.get_default_package_key(payment)
        package = payment["packages"].get(key)
        if not package or not package.get("enabled"):
            return None
        return dict(package)

    async def track_offer_shown(self, **kwargs):
        self.offer_events.append(kwargs)

    async def track_invoice_opened(self, **kwargs):
        self.invoice_events.append(kwargs)

    async def send_premium_invoice(self, message, package_key=None):
        self.invoice_calls += 1
        self.invoice_package_keys.append(package_key or self.get_default_package_key())
        return self.invoice_result

    def build_virtual_checkout_text(self, package_key=None):
        package = self.get_package(package_key)
        return f"Тестовая оплата\n\nТариф: {package['title']}"

    async def process_virtual_payment(self, *, user_id: int, package_key: str | None = None):
        package = self.get_package(package_key)
        self.virtual_payment_calls.append((user_id, package["key"]))
        return {
            "package_title": package["title"],
            "package_key": package["key"],
            "plan_key": package["plan_key"],
            "premium_expires_at": "2026-04-28 12:00:00",
            "is_recurring": False,
            "referral": None,
        }

    def build_success_message(self, result):
        return f"Успешно: {result['package_title']}"


class FakeUserServiceForOffer:
    def __init__(self, user: dict | None = None):
        self.user = user or {
            "id": 123,
            "is_premium": False,
            "subscription_plan": "free",
            "premium_expires_at": None,
        }

    async def get_user(self, user_id: int):
        return dict(self.user)


class FakeAdminSettingsServiceForOffer:
    def get_runtime_settings(self):
        return {
            "payment": {
                "currency": "RUB",
                "default_package_key": "pro_month",
                "price_minor_units": 44900,
                "access_duration_days": 30,
                "packages": build_test_packages(),
                "premium_menu_description_template": "Платные тарифы открывают: {premium_modes_list}. Цена: {price_label} на {access_days_label}. Лимит Premium: {premium_daily_limit}.",
                "premium_menu_packages_title": "Выбери пакет:",
                "premium_menu_package_line_template": "• {title} — {price_label} на {access_days_label}",
                "premium_menu_preview_template": "Пробно: {preview_modes_list}.",
            },
            "limits": {
                "premium_daily_messages_limit": 120,
                "mode_preview_enabled": True,
                "mode_preview_default_limit": 2,
                "mode_daily_limits": {"mentor": 1},
            },
        }

    def get_mode_catalog(self):
        return {
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
            "free_talk": {
                "key": "free_talk",
                "name": "Свободный",
                "icon": "🌘",
                "is_premium": True,
                "sort_order": 40,
            },
        }


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
        self.subscription_grants = []
        self.set_until_calls = []
        self.plan_set_until_calls = []

    async def grant_premium_days(self, user_id: int, days: int) -> str:
        self.grants.append((user_id, days))
        return "2026-04-28 12:00:00"

    async def grant_subscription_days(self, user_id: int, plan_key: str, days: int) -> str:
        self.subscription_grants.append((user_id, plan_key, days))
        self.grants.append((user_id, days))
        return "2026-04-28 12:00:00"

    async def set_premium_until(self, user_id: int, expires_at) -> bool:
        self.set_until_calls.append((user_id, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
        return True

    async def set_subscription_plan_until(self, user_id: int, plan_key: str, expires_at) -> bool:
        formatted = expires_at.strftime("%Y-%m-%d %H:%M:%S")
        self.plan_set_until_calls.append((user_id, plan_key, formatted))
        self.set_until_calls.append((user_id, formatted))
        return True


class FakeSettingsService:
    def get_runtime_settings(self):
        return {
            "payment": {
                "provider_token": "provider-token",
                "currency": "RUB",
                "default_package_key": "pro_month",
                "price_minor_units": 44900,
                "access_duration_days": 30,
                "recurring_stars_enabled": True,
                "packages": build_test_packages(),
                "product_title": "Платный тариф",
                "product_description": "Открой платные режимы.",
                "premium_benefits_text": "Преимущества Premium",
                "buy_cta_text": "Купить Premium",
                "offer_preview_exhausted_template": "Пробный доступ к режиму {mode_name} на сегодня закончился.",
                "premium_menu_description_template": "Premium открывает: {premium_modes_list}.",
                "premium_menu_packages_title": "Выбери пакет:",
                "premium_menu_package_line_template": "• {title} — {price_label} на {access_days_label}",
                "premium_menu_package_button_template": "{title} • {price_label}",
                "premium_menu_preview_template": "Пробно: {preview_modes_list}.",
                "premium_menu_back_button_text": "← К режимам",
                "recurring_button_text": "Открыть оплату",
                "already_premium_message": "Premium уже активен.",
                "unavailable_message": "Оплата сейчас недоступна",
                "invoice_error_message": "Не удалось создать счет",
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
    async def test_show_premium_menu_renders_package_buttons_and_details(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer()
        admin_settings_service = FakeAdminSettingsServiceForOffer()

        result = await show_premium_menu(
            message,
            payment_service,
            user_service,
            admin_settings_service,
            trigger=OFFER_TRIGGER_MODE_LOCKED,
            mode_name="Наставник",
            premium_limit=120,
        )

        self.assertTrue(result)
        self.assertEqual(len(message.answers), 1)
        text = message.answers[0]["text"]
        self.assertIn("Режим Наставник доступен", text)
        self.assertIn("Платные тарифы открывают:", text)
        self.assertIn("Выбери пакет:", text)
        self.assertIn("Premium на 30 дней", text)
        self.assertIn("Пробно:", text)
        keyboard = message.answers[0]["reply_markup"]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            f"{CALLBACK_BUY_PREMIUM}:pro_month:{OFFER_TRIGGER_MODE_LOCKED}",
        )
        self.assertEqual(
            keyboard.inline_keyboard[2][0].callback_data,
            f"{CALLBACK_BUY_PREMIUM}:premium_month:{OFFER_TRIGGER_MODE_LOCKED}",
        )
        self.assertEqual(payment_service.offer_events[0]["trigger"], OFFER_TRIGGER_MODE_LOCKED)

    async def test_show_premium_menu_uses_preview_exhausted_trigger_in_buttons(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer()
        admin_settings_service = FakeAdminSettingsServiceForOffer()

        result = await show_premium_menu(
            message,
            payment_service,
            user_service,
            admin_settings_service,
            trigger=OFFER_TRIGGER_PREVIEW_EXHAUSTED,
            mode_name="Свободный",
            premium_limit=120,
        )

        self.assertTrue(result)
        self.assertIn("Пробный доступ к режиму Свободный", message.answers[0]["text"])
        keyboard = message.answers[0]["reply_markup"]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            f"{CALLBACK_BUY_PREMIUM}:pro_month:{OFFER_TRIGGER_PREVIEW_EXHAUSTED}",
        )

    async def test_show_premium_menu_includes_active_subscription_status(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer(
            {
                "id": 123,
                "is_premium": True,
                "subscription_plan": "premium",
                "premium_expires_at": "2026-04-01 12:00:00",
            }
        )
        admin_settings_service = FakeAdminSettingsServiceForOffer()

        result = await show_premium_menu(message, payment_service, user_service, admin_settings_service)

        self.assertTrue(result)
        self.assertIn("Premium активен до 01.04.2026", message.answers[0]["text"])
        self.assertNotIn("Пробно:", message.answers[0]["text"])

    async def test_send_premium_offer_only_opens_selected_invoice_and_tracks_event(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer()
        user_service = FakeUserServiceForOffer()

        result = await send_premium_offer(
            message,
            payment_service,
            user_service,
            trigger=OFFER_TRIGGER_LIMIT_REACHED,
            premium_limit=120,
            package_key="premium_year",
        )

        self.assertTrue(result)
        self.assertEqual(payment_service.invoice_calls, 1)
        self.assertEqual(payment_service.invoice_package_keys, ["premium_year"])
        self.assertEqual(len(message.answers), 0)
        self.assertEqual(payment_service.offer_events, [])
        self.assertEqual(payment_service.invoice_events[0]["trigger"], OFFER_TRIGGER_LIMIT_REACHED)
        self.assertEqual(payment_service.invoice_events[0]["metadata"]["package_key"], "premium_year")

    async def test_send_premium_offer_reports_invoice_error(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer(invoice_result=False)

        result = await send_premium_offer(message, payment_service, package_key="premium_month")

        self.assertFalse(result)
        self.assertEqual(message.answers[0]["text"], "Не удалось создать счет")

    async def test_send_premium_offer_opens_virtual_checkout_when_virtual_mode_enabled(self):
        message = FakeMessage()
        payment_service = FakePaymentServiceForOffer(virtual_mode=True)

        result = await send_premium_offer(
            message,
            payment_service,
            trigger=OFFER_TRIGGER_LIMIT_REACHED,
            package_key="pro_year",
        )

        self.assertTrue(result)
        self.assertEqual(payment_service.invoice_calls, 0)
        self.assertEqual(len(message.answers), 1)
        self.assertIn("Тестовая оплата", message.answers[0]["text"])
        keyboard = message.answers[0]["reply_markup"]
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            f"{CALLBACK_CONFIRM_VIRTUAL_PAYMENT}:pro_year",
        )
        self.assertEqual(payment_service.invoice_events[0]["metadata"]["payment_mode"], "virtual")

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
                invoice_payload="premium:42:week",
                total_amount=24900,
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
        self.assertEqual(user_service.subscription_grants, [(42, "pro", 30)])
        self.assertEqual(user_service.set_until_calls, [])
        self.assertEqual(payment_repository.saved["amount"], 249.0)
        self.assertEqual(payment_repository.saved["metadata"]["package_key"], "pro_month")
        self.assertEqual(payment_repository.saved["metadata"]["package_title"], "Pro на 30 дней")
        self.assertEqual(payment_repository.saved["metadata"]["plan_key"], "pro")
        self.assertEqual(payment_repository.saved["metadata"]["premium_expires_at"], "2026-04-28 12:00:00")
        self.assertEqual(
            referral_service.calls,
            [
                {
                    "referred_user_id": 42,
                    "amount_minor_units": 24900,
                    "external_payment_id": "tg-charge-1",
                    "is_first_payment": True,
                }
            ],
        )
        self.assertEqual(result["premium_expires_at"], "2026-04-28 12:00:00")
        self.assertEqual(result["package_key"], "pro_month")
        self.assertEqual(result["plan_key"], "pro")
        self.assertEqual(monetization_repository.events[-1]["event_name"], "paid")
        self.assertEqual(monetization_repository.events[-1]["offer_trigger"], "limit_reached")
        self.assertEqual(monetization_repository.events[-1]["offer_variant"], "b")

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
                invoice_payload="premium:42:month",
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
        self.assertEqual(
            user_service.plan_set_until_calls,
            [(42, "premium", subscription_expires_at.strftime("%Y-%m-%d %H:%M:%S"))],
        )
        self.assertTrue(result["is_recurring"])
        self.assertEqual(result["package_key"], "premium_month")
        self.assertEqual(result["plan_key"], "premium")
        self.assertEqual(monetization_repository.events[-1]["event_name"], "renewed")
        self.assertEqual(monetization_repository.events[-1]["offer_variant"], "b")

    async def test_process_virtual_payment_grants_days_and_saves_virtual_record(self):
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

        result = await service.process_virtual_payment(user_id=42, package_key="pro_month")

        self.assertEqual(user_service.grants, [(42, 30)])
        self.assertEqual(user_service.subscription_grants, [(42, "pro", 30)])
        self.assertEqual(payment_repository.saved["provider"], "virtual")
        self.assertEqual(payment_repository.saved["currency"], "RUB")
        self.assertEqual(payment_repository.saved["metadata"]["virtual_payment"], True)
        self.assertEqual(payment_repository.saved["metadata"]["plan_key"], "pro")
        self.assertEqual(result["package_key"], "pro_month")
        self.assertEqual(result["plan_key"], "pro")
        self.assertEqual(monetization_repository.events[-1]["event_name"], "paid")


class PaymentFormattingTests(unittest.TestCase):
    def test_build_success_message_includes_expiry_and_package(self):
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
                "package_title": "Premium на 30 дней",
                "plan_key": "premium",
                "premium_expires_at": "2026-04-28 12:00:00",
                "is_recurring": False,
            }
        )

        self.assertIn("Payment success", text)
        self.assertIn("Premium на 30 дней", text)
        self.assertIn("План Premium уже активен.", text)
        self.assertIn("28.04.2026 12:00 UTC", text)


class ModesKeyboardTests(unittest.TestCase):
    def test_modes_keyboard_adds_premium_menu_button_for_non_premium_user(self):
        keyboard = get_modes_keyboard(
            {"is_premium": False},
            {"ui": {"premium_button_text": "💎 Premium"}, "limits": {}, "payment": {}},
        )

        self.assertEqual(keyboard.inline_keyboard[-1][0].callback_data, CALLBACK_OPEN_PREMIUM_MENU)
        self.assertEqual(keyboard.inline_keyboard[-1][0].text, "💎 Premium")

    def test_modes_keyboard_hides_buy_button_for_premium_user(self):
        keyboard = get_modes_keyboard(
            {"is_premium": True},
            {"ui": {"premium_button_text": "💎 Premium"}, "limits": {}, "payment": {}},
        )

        callback_data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        self.assertNotIn(CALLBACK_OPEN_PREMIUM_MENU, callback_data)

    def test_modes_keyboard_marks_locked_modes_but_keeps_button_clean(self):
        keyboard = get_modes_keyboard(
            {"is_premium": False},
            {
                "ui": {
                    "premium_button_text": "💎 Premium",
                    "modes_premium_marker": "🔒",
                },
                "limits": {},
                "payment": {},
            },
            {
                "base": {
                    "key": "base",
                    "name": "Базовый",
                    "icon": "💬",
                    "is_premium": False,
                    "sort_order": 10,
                },
                "mentor": {
                    "key": "mentor",
                    "name": "Наставник",
                    "icon": "🧠",
                    "is_premium": True,
                    "sort_order": 20,
                },
            },
        )

        texts = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("🧠 Наставник 🔒", texts)
        self.assertEqual(keyboard.inline_keyboard[-1][0].text, "💎 Premium")

    def test_build_modes_menu_text_returns_clean_catalog_title(self):
        text = build_modes_menu_text(
            {"is_premium": False},
            {
                "ui": {
                    "modes_title": "Выбери режим",
                    "modes_menu_premium_text": "Не должно отображаться",
                    "modes_menu_preview_text": "Не должно отображаться",
                },
                "limits": {},
                "payment": {},
            },
            {},
        )

        self.assertEqual(text, "Выбери режим")


class ModeAccessServiceTests(unittest.TestCase):
    def test_default_preview_limit_applies_to_new_premium_modes(self):
        service = ModeAccessService()
        runtime_settings = {
            "limits": {
                "mode_preview_enabled": True,
                "mode_preview_default_limit": 2,
                "mode_daily_limits": {"mentor": 1},
            }
        }
        mode_catalog = {
            "free_talk": {"is_premium": True},
            "mentor": {"is_premium": True},
        }
        user = {"is_premium": False}
        state = {}

        status = service.get_selection_status(
            user=user,
            mode_key="free_talk",
            state=state,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )

        self.assertTrue(status["allowed"])
        self.assertEqual(status["daily_limit"], 2)

        state = service.register_successful_message(
            state,
            mode_key="free_talk",
            user=user,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        state = service.register_successful_message(
            state,
            mode_key="free_talk",
            user=user,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )

        status = service.get_selection_status(
            user=user,
            mode_key="free_talk",
            state=state,
            runtime_settings=runtime_settings,
            mode_catalog=mode_catalog,
        )
        self.assertFalse(status["allowed"])
        self.assertEqual(status["remaining"], 0)
