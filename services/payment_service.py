from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

from services.payment_formatting import format_access_days_label, format_package_price_label


class PaymentService:
    RECURRING_STARS_PERIOD_SECONDS = 30 * 24 * 60 * 60
    DEFAULT_PACKAGE_CATALOG = {
        "day": {
            "enabled": True,
            "title": "Premium на 1 день",
            "description": "Короткий доступ, чтобы проверить все режимы и снять лимиты на день.",
            "price_minor_units": 7900,
            "access_duration_days": 1,
            "sort_order": 10,
            "badge": "Тест",
            "recurring_stars_enabled": False,
        },
        "week": {
            "enabled": True,
            "title": "Premium на 7 дней",
            "description": "Неделя полного доступа ко всем режимам и увеличенному лимиту сообщений.",
            "price_minor_units": 24900,
            "access_duration_days": 7,
            "sort_order": 20,
            "badge": "Популярно",
            "recurring_stars_enabled": False,
        },
        "month": {
            "enabled": True,
            "title": "Premium на 30 дней",
            "description": "Основная подписка на месяц со всеми режимами и повышенным лимитом.",
            "price_minor_units": 49900,
            "access_duration_days": 30,
            "sort_order": 30,
            "badge": "Основной",
            "recurring_stars_enabled": True,
        },
        "year": {
            "enabled": True,
            "title": "Premium на 365 дней",
            "description": "Максимально выгодный вариант для долгого доступа без продлений каждый месяц.",
            "price_minor_units": 399000,
            "access_duration_days": 365,
            "sort_order": 40,
            "badge": "Выгодно",
            "recurring_stars_enabled": False,
        },
    }

    def __init__(
        self,
        settings,
        payment_repository,
        user_service,
        settings_service,
        referral_service,
        monetization_repository=None,
    ):
        self.settings = settings
        self.payment_repository = payment_repository
        self.monetization_repository = monetization_repository
        self.user_service = user_service
        self.settings_service = settings_service
        self.referral_service = referral_service

    def get_offer_variant(self, user_id: int) -> str:
        return "a" if user_id % 2 == 0 else "b"

    def get_payment_settings(self) -> dict:
        runtime = self.settings_service.get_runtime_settings()
        payment = deepcopy(runtime["payment"])

        if not payment.get("provider_token"):
            payment["provider_token"] = self.settings.payment_provider_token
        if not payment.get("currency"):
            payment["currency"] = self.settings.payment_currency or "RUB"
        if not payment.get("price_minor_units"):
            payment["price_minor_units"] = self.settings.premium_price_minor_units
        if not payment.get("product_title"):
            payment["product_title"] = self.settings.premium_product_title
        if not payment.get("product_description"):
            payment["product_description"] = self.settings.premium_product_description

        return self._normalize_payment_settings(payment)

    def get_enabled_packages(self, payment_settings: dict | None = None) -> list[dict]:
        payment = self._normalize_payment_settings(payment_settings or self.get_payment_settings())
        packages = [
            dict(package)
            for package in payment["packages"].values()
            if bool(package.get("enabled"))
        ]
        packages.sort(
            key=lambda item: (
                int(item.get("sort_order", 0)),
                str(item.get("title") or item.get("key") or "").lower(),
            )
        )
        return packages

    def uses_virtual_payments(self, payment_settings: dict | None = None) -> bool:
        payment = self._normalize_payment_settings(payment_settings or self.get_payment_settings())
        return str(payment.get("mode") or "telegram").strip().lower() == "virtual"

    def get_default_package_key(self, payment_settings: dict | None = None) -> str:
        payment = self._normalize_payment_settings(payment_settings or self.get_payment_settings())
        default_key = str(payment.get("default_package_key") or "").strip().lower()
        if default_key in payment["packages"] and payment["packages"][default_key].get("enabled"):
            return default_key

        for package in self.get_enabled_packages(payment):
            if package.get("is_default"):
                return str(package["key"])

        enabled = self.get_enabled_packages(payment)
        if enabled:
            return str(enabled[0]["key"])
        return "month"

    def get_default_package(self, payment_settings: dict | None = None) -> dict | None:
        payment = self._normalize_payment_settings(payment_settings or self.get_payment_settings())
        return self.get_package(self.get_default_package_key(payment), payment)

    def get_package(self, package_key: str | None, payment_settings: dict | None = None) -> dict | None:
        payment = self._normalize_payment_settings(payment_settings or self.get_payment_settings())
        normalized_key = str(package_key or "").strip().lower() or self.get_default_package_key(payment)
        package = payment["packages"].get(normalized_key)
        if not package or not package.get("enabled"):
            return None
        return dict(package)

    def is_enabled(self) -> bool:
        payment = self.get_payment_settings()
        if not self.get_enabled_packages(payment):
            return False
        if self.uses_virtual_payments(payment):
            return True
        if payment["currency"].upper() == "XTR":
            return any(int(package.get("price_minor_units", 0)) > 0 for package in self.get_enabled_packages(payment))
        return bool(str(payment.get("provider_token") or "").strip())

    def build_invoice_payload(self, user_id: int, package_key: str | None = None) -> str:
        safe_package_key = str(package_key or self.get_default_package_key()).strip().lower()
        return f"premium:{user_id}:{safe_package_key}"

    def validate_invoice_payload(self, payload: str, user_id: int) -> bool:
        parsed = self.parse_invoice_payload(payload)
        if not parsed:
            return False
        if parsed["user_id"] != int(user_id):
            return False
        return self.get_package(parsed["package_key"]) is not None

    def parse_invoice_payload(self, payload: str | None) -> dict | None:
        raw = str(payload or "").strip()
        if not raw.startswith("premium:"):
            return None

        parts = raw.split(":")
        if len(parts) == 2:
            try:
                return {
                    "user_id": int(parts[1]),
                    "package_key": self.get_default_package_key(),
                }
            except ValueError:
                return None

        if len(parts) != 3:
            return None

        try:
            return {
                "user_id": int(parts[1]),
                "package_key": str(parts[2]).strip().lower(),
            }
        except ValueError:
            return None

    def build_prices(self, package_key: str | None = None) -> list[LabeledPrice]:
        payment = self.get_payment_settings()
        package = self.get_package(package_key, payment)
        if package is None:
            return []
        return [
            LabeledPrice(
                label=str(package.get("title") or payment["product_title"]).strip(),
                amount=int(package["price_minor_units"]),
            )
        ]

    def uses_recurring_stars_subscription(self, package_key: str | None = None) -> bool:
        payment = self.get_payment_settings()
        package = self.get_package(package_key, payment)
        if package is None:
            return False
        return (
            bool(package.get("recurring_stars_enabled"))
            and payment["currency"].upper() == "XTR"
            and int(package.get("access_duration_days", 30)) == 30
        )

    def build_subscription_status_text(self, user: dict | None) -> str:
        payment = self.get_payment_settings()
        if not user or not user.get("is_premium"):
            return ""

        expires_at = str(user.get("premium_expires_at") or "").strip()
        status_text = str(payment.get("already_premium_message") or "").strip()
        if not expires_at:
            return status_text

        expires_text = self.format_expiry_text(expires_at)
        if not expires_text:
            return status_text

        if status_text:
            return f"{status_text}\nPremium активен до {expires_text}."
        return f"Premium активен до {expires_text}."

    async def send_premium_invoice(self, message: Message, package_key: str | None = None) -> bool:
        payment = self.get_payment_settings()
        package = self.get_package(package_key, payment)
        if not self.is_enabled() or package is None:
            return False

        title = str(package.get("title") or payment["product_title"]).strip()
        description = str(package.get("description") or payment["product_description"]).strip()
        payload = self.build_invoice_payload(message.from_user.id, package["key"])
        prices = self.build_prices(package["key"])
        if not prices:
            return False

        if self.uses_recurring_stars_subscription(package["key"]):
            invoice_link = await message.bot.create_invoice_link(
                title=title,
                description=description,
                payload=payload,
                provider_token="",
                currency="XTR",
                prices=prices,
                subscription_period=self.RECURRING_STARS_PERIOD_SECONDS,
            )
            await message.answer(
                "Оплата откроется по кнопке ниже.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=str(payment.get("recurring_button_text") or "Открыть оплату").strip(),
                                url=invoice_link,
                            )
                        ]
                    ]
                ),
            )
            return True

        provider_token = str(payment.get("provider_token") or "").strip()
        if payment["currency"].upper() == "XTR":
            provider_token = ""
        if payment["currency"].upper() != "XTR" and not provider_token:
            return False

        await message.answer_invoice(
            title=title,
            description=description,
            payload=payload,
            provider_token=provider_token,
            currency=payment["currency"],
            prices=prices,
        )
        return True

    def build_virtual_checkout_text(self, package_key: str | None = None) -> str:
        payment = self.get_payment_settings()
        package = self.get_package(package_key, payment)
        if package is None:
            return str(payment.get("invoice_error_message") or "").strip()

        access_days = int(package.get("access_duration_days", 30))
        access_days_label = format_access_days_label(access_days)
        price_label = format_package_price_label(package, payment)
        template = str(
            payment.get("virtual_payment_description_template")
            or ""
        ).strip()
        if template:
            try:
                return template.format(
                    package_key=package["key"],
                    package_title=package["title"],
                    price_label=price_label,
                    access_days=access_days,
                    access_days_label=access_days_label,
                    description=package.get("description", ""),
                ).strip()
            except (KeyError, ValueError):
                pass

        return (
            f"Тестовый checkout\n\n"
            f"Тариф: {package['title']}\n"
            f"Цена: {price_label}\n"
            f"Срок доступа: {access_days_label}\n\n"
            f"Это виртуальная оплата для запуска и проверки воронки.\n"
            f"Реального списания не будет, но покупка сохранится в истории оплат."
        )

    async def process_virtual_payment(
        self,
        *,
        user_id: int,
        package_key: str | None = None,
    ) -> dict:
        payment = self.get_payment_settings()
        package = self.get_package(package_key, payment)
        if package is None:
            raise ValueError("Unknown premium package")

        external_payment_id = f"virtual-{user_id}-{package['key']}-{uuid4().hex[:12]}"
        amount_minor_units = int(package.get("price_minor_units", 0))
        amount = self._to_major_units(amount_minor_units, payment["currency"])
        premium_expires_at = await self.user_service.grant_premium_days(
            user_id,
            int(package.get("access_duration_days", 30)),
        )
        payment_info = await self.payment_repository.save_payment(
            user_id=user_id,
            provider="virtual",
            external_payment_id=external_payment_id,
            amount=amount,
            currency=payment["currency"],
            status="paid",
            paid_at=None,
            metadata={
                "invoice_payload": self.build_invoice_payload(user_id, package["key"]),
                "provider_payment_charge_id": None,
                "total_amount_minor_units": amount_minor_units,
                "subscription_expiration_date": None,
                "is_recurring": False,
                "is_first_recurring": False,
                "premium_expires_at": premium_expires_at,
                "package_key": package["key"],
                "package_title": package["title"],
                "access_duration_days": int(package.get("access_duration_days", 30)),
                "package_price_minor_units": amount_minor_units,
                "virtual_payment": True,
            },
        )

        referral_result = await self.referral_service.process_successful_payment(
            referred_user_id=user_id,
            amount_minor_units=amount_minor_units,
            external_payment_id=external_payment_id,
            is_first_payment=bool(payment_info["is_first_payment"]),
        )
        synthetic_payment = SimpleNamespace(
            telegram_payment_charge_id=external_payment_id,
            currency=payment["currency"],
            total_amount=amount_minor_units,
            is_recurring=False,
            is_first_recurring=False,
        )
        await self._track_successful_payment_event(
            user_id=user_id,
            payment=synthetic_payment,
            payment_info=payment_info,
            package=package,
        )
        return {
            "payment": payment_info,
            "referral": referral_result,
            "premium_expires_at": premium_expires_at,
            "is_recurring": False,
            "is_first_recurring": False,
            "package_key": package["key"],
            "package_title": package["title"],
            "virtual_payment": True,
        }

    async def track_offer_shown(
        self,
        *,
        user_id: int,
        trigger: str,
        variant: str,
        metadata: dict | None = None,
    ) -> None:
        if self.monetization_repository is None:
            return
        await self.monetization_repository.log_event(
            user_id=user_id,
            event_name="offer_shown",
            offer_trigger=trigger,
            offer_variant=variant,
            metadata=metadata,
        )

    async def track_invoice_opened(
        self,
        *,
        user_id: int,
        trigger: str,
        variant: str,
        metadata: dict | None = None,
    ) -> None:
        if self.monetization_repository is None:
            return
        await self.monetization_repository.log_event(
            user_id=user_id,
            event_name="invoice_opened",
            offer_trigger=trigger,
            offer_variant=variant,
            metadata=metadata,
        )

    async def handle_successful_payment(self, message: Message) -> dict | None:
        payment = message.successful_payment
        if payment is None:
            return None

        user_id = message.from_user.id
        payload = self.parse_invoice_payload(payment.invoice_payload)
        if payload is None or not self.validate_invoice_payload(payment.invoice_payload, user_id):
            raise ValueError("Invalid invoice payload")

        package = self.get_package(payload["package_key"])
        if package is None:
            raise ValueError("Unknown premium package")

        amount = self._to_major_units(payment.total_amount, payment.currency)
        premium_expires_at = await self._apply_premium_access(user_id, payment, package)
        payment_info = await self.payment_repository.save_payment(
            user_id=user_id,
            provider="telegram",
            external_payment_id=payment.telegram_payment_charge_id,
            amount=amount,
            currency=payment.currency,
            status="paid",
            paid_at=None,
            metadata={
                "invoice_payload": payment.invoice_payload,
                "provider_payment_charge_id": payment.provider_payment_charge_id,
                "total_amount_minor_units": payment.total_amount,
                "subscription_expiration_date": payment.subscription_expiration_date,
                "is_recurring": bool(payment.is_recurring),
                "is_first_recurring": bool(payment.is_first_recurring),
                "premium_expires_at": premium_expires_at,
                "package_key": package["key"],
                "package_title": package["title"],
                "access_duration_days": int(package.get("access_duration_days", 30)),
                "package_price_minor_units": int(package.get("price_minor_units", 0)),
            },
        )

        referral_result = await self.referral_service.process_successful_payment(
            referred_user_id=user_id,
            amount_minor_units=payment.total_amount,
            external_payment_id=payment.telegram_payment_charge_id,
            is_first_payment=bool(payment_info["is_first_payment"]),
        )
        await self._track_successful_payment_event(
            user_id=user_id,
            payment=payment,
            payment_info=payment_info,
            package=package,
        )
        return {
            "payment": payment_info,
            "referral": referral_result,
            "premium_expires_at": premium_expires_at,
            "is_recurring": bool(payment.is_recurring),
            "is_first_recurring": bool(payment.is_first_recurring),
            "package_key": package["key"],
            "package_title": package["title"],
        }

    def build_success_message(self, result: dict | None) -> str:
        payment = self.get_payment_settings()
        base_message = str(payment["success_message"]).strip()
        if not result:
            return base_message

        parts = [base_message] if base_message else []
        package_title = str(result.get("package_title") or "").strip()
        if package_title:
            parts.append(f"Тариф: {package_title}.")

        premium_expires_at = str(result.get("premium_expires_at") or "").strip()
        if premium_expires_at:
            expires_text = self.format_expiry_text(premium_expires_at)
            if expires_text:
                parts.append(f"Доступ активен до {expires_text}.")
        if result.get("is_recurring"):
            parts.append("Подписка будет продлеваться через Telegram Stars, пока она активна.")
        return "\n\n".join(parts)

    async def _apply_premium_access(self, user_id: int, payment, package: dict) -> str | None:
        subscription_expiration_date = getattr(payment, "subscription_expiration_date", None)
        if subscription_expiration_date:
            expires_at = datetime.fromtimestamp(subscription_expiration_date, tz=timezone.utc)
            await self.user_service.set_premium_until(user_id, expires_at)
            return expires_at.strftime("%Y-%m-%d %H:%M:%S")

        access_duration_days = int(package.get("access_duration_days", 30))
        return await self.user_service.grant_premium_days(user_id, access_duration_days)

    def format_expiry_text(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return ""
        return dt.strftime("%d.%m.%Y %H:%M UTC")

    def _to_major_units(self, total_amount: int, currency: str) -> float:
        if currency.upper() == "XTR":
            return float(total_amount)
        return float(total_amount) / 100.0

    async def _track_successful_payment_event(
        self,
        *,
        user_id: int,
        payment,
        payment_info: dict,
        package: dict,
    ) -> None:
        if self.monetization_repository is None:
            return

        event_name = "paid" if payment_info.get("is_first_payment") else "renewed"
        latest_offer_context = await self.monetization_repository.get_latest_offer_context(user_id)
        await self.monetization_repository.log_event(
            user_id=user_id,
            event_name=event_name,
            offer_trigger=(latest_offer_context or {}).get("offer_trigger"),
            offer_variant=(latest_offer_context or {}).get("offer_variant"),
            payment_external_id=payment.telegram_payment_charge_id,
            metadata={
                "currency": payment.currency,
                "total_amount": payment.total_amount,
                "is_recurring": bool(getattr(payment, "is_recurring", False)),
                "is_first_payment": bool(payment_info.get("is_first_payment")),
                "package_key": package["key"],
                "package_title": package["title"],
            },
        )

    def _normalize_payment_settings(self, payment_settings: dict) -> dict:
        payment = deepcopy(payment_settings)
        payment["provider_token"] = str(payment.get("provider_token") or "").strip()
        payment["mode"] = str(payment.get("mode") or "telegram").strip().lower() or "telegram"
        if payment["mode"] not in {"telegram", "virtual"}:
            payment["mode"] = "telegram"
        payment["currency"] = str(payment.get("currency") or "RUB").strip().upper() or "RUB"
        payment["product_title"] = str(payment.get("product_title") or "Premium").strip() or "Premium"
        payment["product_description"] = str(payment.get("product_description") or "").strip()
        payment["recurring_stars_enabled"] = bool(payment.get("recurring_stars_enabled", True))

        normalized_packages: dict[str, dict] = {}
        raw_packages = payment.get("packages")
        if not isinstance(raw_packages, dict) or not raw_packages:
            raw_packages = self._build_legacy_packages(payment)

        for package_key, defaults in self.DEFAULT_PACKAGE_CATALOG.items():
            raw_value = raw_packages.get(package_key, {})
            if not isinstance(raw_value, dict):
                raw_value = {}

            package = deepcopy(defaults)
            package.update(raw_value)
            package["key"] = package_key
            package["enabled"] = bool(package.get("enabled", True))
            package["title"] = str(package.get("title") or defaults["title"]).strip() or defaults["title"]
            package["description"] = str(package.get("description") or "").strip()
            package["price_minor_units"] = max(1, int(package.get("price_minor_units", defaults["price_minor_units"])))
            package["access_duration_days"] = max(
                1,
                int(package.get("access_duration_days", defaults["access_duration_days"])),
            )
            package["sort_order"] = int(package.get("sort_order", defaults["sort_order"]))
            package["badge"] = str(package.get("badge") or "").strip()
            package["is_default"] = bool(package.get("is_default", False))
            package["recurring_stars_enabled"] = bool(
                package.get("recurring_stars_enabled", payment["recurring_stars_enabled"])
            )
            normalized_packages[package_key] = package

        payment["packages"] = normalized_packages
        payment["default_package_key"] = self._resolve_default_package_key(payment)
        default_package = payment["packages"][payment["default_package_key"]]
        payment["price_minor_units"] = int(default_package["price_minor_units"])
        payment["access_duration_days"] = int(default_package["access_duration_days"])
        return payment

    def _resolve_default_package_key(self, payment: dict) -> str:
        requested_key = str(payment.get("default_package_key") or "").strip().lower()
        if requested_key in payment["packages"] and payment["packages"][requested_key].get("enabled"):
            return requested_key

        for package_key, package in payment["packages"].items():
            if package.get("enabled") and package.get("is_default"):
                return package_key

        for package in sorted(
            payment["packages"].values(),
            key=lambda item: (int(item.get("sort_order", 0)), item["key"]),
        ):
            if package.get("enabled"):
                return str(package["key"])
        return "month"

    def _build_legacy_packages(self, payment: dict) -> dict:
        packages = deepcopy(self.DEFAULT_PACKAGE_CATALOG)
        default_key = str(payment.get("default_package_key") or "month").strip().lower()
        if default_key not in packages:
            default_key = "month"

        packages[default_key]["price_minor_units"] = max(1, int(payment.get("price_minor_units", 49900) or 49900))
        packages[default_key]["access_duration_days"] = max(
            1,
            int(payment.get("access_duration_days", 30) or 30),
        )
        packages[default_key]["title"] = str(
            payment.get("product_title") or packages[default_key]["title"]
        ).strip() or packages[default_key]["title"]
        packages[default_key]["description"] = str(
            payment.get("product_description") or packages[default_key]["description"]
        ).strip()
        packages[default_key]["is_default"] = True
        packages[default_key]["recurring_stars_enabled"] = bool(payment.get("recurring_stars_enabled", True))
        return packages
