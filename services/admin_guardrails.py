from __future__ import annotations

import hashlib
import hmac
from typing import Any


MAX_BROADCAST_RECIPIENTS = 100


def normalize_broadcast_user_ids(raw_user_ids: Any, *, max_recipients: int = MAX_BROADCAST_RECIPIENTS) -> list[int]:
    if not isinstance(raw_user_ids, list):
        return []

    normalized: list[int] = []
    seen: set[int] = set()
    for value in raw_user_ids:
        try:
            user_id = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in seen:
            continue
        normalized.append(user_id)
        seen.add(user_id)
        if len(normalized) >= max_recipients:
            break
    return normalized


def build_broadcast_confirmation_token(user_ids: list[int], text: str, *, secret: str) -> str:
    normalized_ids = ",".join(str(user_id) for user_id in sorted(set(int(user_id) for user_id in user_ids)))
    payload = f"{normalized_ids}\n{text.strip()}"
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_broadcast_preview(
    user_ids: list[int],
    text: str,
    *,
    secret: str,
) -> dict[str, Any]:
    normalized_text = str(text or "").strip()
    normalized_ids = [int(user_id) for user_id in user_ids]
    warnings: list[str] = []

    if len(normalized_ids) >= 20:
        warnings.append("Большая рассылка: проверь выбор получателей еще раз.")
    if len(normalized_text) >= 500:
        warnings.append("Длинное сообщение: убедись, что текст не перегружает пользователя.")
    if "http://" in normalized_text or "https://" in normalized_text or "t.me/" in normalized_text:
        warnings.append("В тексте есть ссылка: проверь, что она уместна для массовой отправки.")

    return {
        "phase": "preview",
        "requested_count": len(normalized_ids),
        "preview_text": normalized_text[:500],
        "truncated": len(normalized_text) > 500,
        "warnings": warnings,
        "confirmation_token": build_broadcast_confirmation_token(
            normalized_ids,
            normalized_text,
            secret=secret,
        ),
    }
