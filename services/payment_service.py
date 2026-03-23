from aiogram.types import LabeledPrice, Message


class PaymentService:
    def __init__(self, settings, payment_repository, user_service):
        self.settings = settings
        self.payment_repository = payment_repository
        self.user_service = user_service

    def is_enabled(self) -> bool:
        return bool(self.settings.payment_provider_token.strip())

    def build_invoice_payload(self, user_id: int) -> str:
        return f"premium:{user_id}"

    def build_prices(self) -> list[LabeledPrice]:
        return [
            LabeledPrice(
                label=self.settings.premium_product_title,
                amount=self.settings.premium_price_minor_units,
            )
        ]

    async def send_premium_invoice(self, message: Message) -> bool:
        if not self.is_enabled():
            return False

        await message.answer_invoice(
            title=self.settings.premium_product_title,
            description=self.settings.premium_product_description,
            payload=self.build_invoice_payload(message.from_user.id),
            provider_token=self.settings.payment_provider_token,
            currency=self.settings.payment_currency,
            prices=self.build_prices(),
        )
        return True

    async def handle_successful_payment(self, message: Message) -> None:
        payment = message.successful_payment
        if payment is None:
            return

        user_id = message.from_user.id
        amount = self._to_major_units(payment.total_amount, payment.currency)

        await self.payment_repository.save_payment(
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

    def _to_major_units(self, total_amount: int, currency: str) -> float:
        if currency.upper() == "XTR":
            return float(total_amount)
        return float(total_amount) / 100.0
