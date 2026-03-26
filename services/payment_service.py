from aiogram.types import LabeledPrice, Message


class PaymentService:
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
        return bool(self.get_payment_settings()["provider_token"].strip())

    def build_invoice_payload(self, user_id: int) -> str:
        return f"premium:{user_id}"

    def validate_invoice_payload(self, payload: str, user_id: int) -> bool:
        return payload == self.build_invoice_payload(user_id)

    def build_prices(self) -> list[LabeledPrice]:
        payment = self.get_payment_settings()
        return [LabeledPrice(label=payment["product_title"], amount=payment["price_minor_units"])]

    async def send_premium_invoice(self, message: Message) -> bool:
        payment = self.get_payment_settings()
        if not payment["provider_token"]:
            return False

        await message.answer_invoice(
            title=payment["product_title"],
            description=payment["product_description"],
            payload=self.build_invoice_payload(message.from_user.id),
            provider_token=payment["provider_token"],
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
            },
        )
        await self.user_service.set_premium(user_id, True)

        referral_result = await self.referral_service.process_successful_payment(
            referred_user_id=user_id,
            amount_minor_units=payment.total_amount,
            external_payment_id=payment.telegram_payment_charge_id,
            is_first_payment=bool(payment_info["is_first_payment"]),
        )
        return {
            "payment": payment_info,
            "referral": referral_result,
        }

    def _to_major_units(self, total_amount: int, currency: str) -> float:
        if currency.upper() == "XTR":
            return float(total_amount)
        return float(total_amount) / 100.0
