from datetime import datetime, timezone

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
)


class PaymentService:
    RECURRING_STARS_PERIOD_SECONDS = 30 * 24 * 60 * 60

    def __init__(
        self,
        settings,
        payment_repository,
        user_service,
        settings_service,
        referral_service,
    ):
        self.settings = settings
        self.payment_repository = payment_repository
        self.user_service = user_service
        self.settings_service = settings_service
        self.referral_service = referral_service

    def get_payment_settings(self) -> dict:
        runtime = self.settings_service.get_runtime_settings()
        payment = runtime["payment"].copy()

        if not payment["provider_token"]:
            payment["provider_token"] = self.settings.payment_provider_token
        if not payment["currency"]:
            payment["currency"] = self.settings.payment_currency or "RUB"
        if not payment["price_minor_units"]:
            payment["price_minor_units"] = self.settings.premium_price_minor_units
        if not payment["product_title"]:
            payment["product_title"] = self.settings.premium_product_title
        if not payment["product_description"]:
            payment["product_description"] = self.settings.premium_product_description
        return payment

    def is_enabled(self) -> bool:
        payment = self.get_payment_settings()
        if payment["currency"].upper() == "XTR":
            return int(payment["price_minor_units"]) > 0
        return bool(payment["provider_token"].strip())

    def build_invoice_payload(self, user_id: int) -> str:
        return f"premium:{user_id}"

    def validate_invoice_payload(self, payload: str, user_id: int) -> bool:
        return payload == self.build_invoice_payload(user_id)

    def build_prices(self) -> list[LabeledPrice]:
        payment = self.get_payment_settings()
        return [LabeledPrice(label=payment["product_title"], amount=payment["price_minor_units"])]

    def uses_recurring_stars_subscription(self) -> bool:
        payment = self.get_payment_settings()
        return (
            bool(payment.get("recurring_stars_enabled"))
            and payment["currency"].upper() == "XTR"
            and int(payment.get("access_duration_days", 30)) == 30
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

    async def send_premium_invoice(self, message: Message) -> bool:
        payment = self.get_payment_settings()
        if not self.is_enabled():
            return False

        if self.uses_recurring_stars_subscription():
            invoice_link = await message.bot.create_invoice_link(
                title=payment["product_title"],
                description=payment["product_description"],
                payload=self.build_invoice_payload(message.from_user.id),
                provider_token="",
                currency="XTR",
                prices=self.build_prices(),
                subscription_period=self.RECURRING_STARS_PERIOD_SECONDS,
            )
            await message.answer(
                "Оплата откроется по кнопке ниже.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=payment["recurring_button_text"],
                                url=invoice_link,
                            )
                        ]
                    ]
                ),
            )
            return True

        provider_token = payment["provider_token"]
        if payment["currency"].upper() == "XTR":
            provider_token = ""
        if payment["currency"].upper() != "XTR" and not provider_token:
            return False

        await message.answer_invoice(
            title=payment["product_title"],
            description=payment["product_description"],
            payload=self.build_invoice_payload(message.from_user.id),
            provider_token=provider_token,
            currency=payment["currency"],
            prices=self.build_prices(),
        )
        return True

    async def handle_successful_payment(self, message: Message) -> dict | None:
        payment = message.successful_payment
        if payment is None:
            return None

        user_id = message.from_user.id
        if not self.validate_invoice_payload(payment.invoice_payload, user_id):
            raise ValueError("Invalid invoice payload")

        amount = self._to_major_units(payment.total_amount, payment.currency)
        premium_expires_at = await self._apply_premium_access(user_id, payment)
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
                "access_duration_days": int(self.get_payment_settings().get("access_duration_days", 30)),
            },
        )

        referral_result = await self.referral_service.process_successful_payment(
            referred_user_id=user_id,
            amount_minor_units=payment.total_amount,
            external_payment_id=payment.telegram_payment_charge_id,
            is_first_payment=bool(payment_info["is_first_payment"]),
        )
        return {
            "payment": payment_info,
            "referral": referral_result,
            "premium_expires_at": premium_expires_at,
            "is_recurring": bool(payment.is_recurring),
            "is_first_recurring": bool(payment.is_first_recurring),
        }

    def build_success_message(self, result: dict | None) -> str:
        payment = self.get_payment_settings()
        base_message = str(payment["success_message"]).strip()
        if not result:
            return base_message

        parts = [base_message] if base_message else []
        premium_expires_at = str(result.get("premium_expires_at") or "").strip()
        if premium_expires_at:
            expires_text = self.format_expiry_text(premium_expires_at)
            if expires_text:
                parts.append(f"Доступ активен до {expires_text}.")
        if result.get("is_recurring"):
            parts.append("Подписка будет продлеваться через Telegram Stars, пока она активна.")
        return "\n\n".join(parts)

    async def _apply_premium_access(self, user_id: int, payment) -> str | None:
        subscription_expiration_date = getattr(payment, "subscription_expiration_date", None)
        if subscription_expiration_date:
            expires_at = datetime.fromtimestamp(subscription_expiration_date, tz=timezone.utc)
            await self.user_service.set_premium_until(user_id, expires_at)
            return expires_at.strftime("%Y-%m-%d %H:%M:%S")

        access_duration_days = int(self.get_payment_settings().get("access_duration_days", 30))
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
