from collections.abc import Mapping
from typing import Any


def format_minor_price_label(amount_minor_units: int | str | None, currency: str | None) -> str:
    safe_currency = str(currency or "RUB").upper()
    safe_amount = int(amount_minor_units or 0)
    if safe_currency == "XTR":
        return f"{safe_amount} {safe_currency}"
    return f"{safe_amount / 100:.2f} {safe_currency}"


def format_price_label(payment_settings: Mapping[str, Any] | None) -> str:
    settings = payment_settings or {}
    return format_minor_price_label(
        settings.get("price_minor_units", 0),
        settings.get("currency") or "RUB",
    )


def format_access_days_label(access_days: int | str | None) -> str:
    days = max(1, int(access_days or 1))
    remainder_100 = days % 100
    remainder_10 = days % 10

    if 11 <= remainder_100 <= 14:
        suffix = "дней"
    elif remainder_10 == 1:
        suffix = "день"
    elif 2 <= remainder_10 <= 4:
        suffix = "дня"
    else:
        suffix = "дней"

    return f"{days} {suffix}"


def format_package_price_label(
    package: Mapping[str, Any] | None,
    payment_settings: Mapping[str, Any] | None,
) -> str:
    settings = payment_settings or {}
    item = package or {}
    return format_minor_price_label(
        item.get("price_minor_units", settings.get("price_minor_units", 0)),
        settings.get("currency") or "RUB",
    )
