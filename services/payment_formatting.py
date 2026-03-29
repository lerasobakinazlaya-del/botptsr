from collections.abc import Mapping
from typing import Any


def format_price_label(payment_settings: Mapping[str, Any] | None) -> str:
    settings = payment_settings or {}
    currency = str(settings.get("currency") or "RUB").upper()
    amount_minor_units = int(settings.get("price_minor_units", 0) or 0)
    if currency == "XTR":
        return f"{amount_minor_units} {currency}"
    return f"{amount_minor_units / 100:.2f} {currency}"


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
