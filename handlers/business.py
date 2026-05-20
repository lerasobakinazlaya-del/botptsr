from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiogram import Router
from aiogram.types import BusinessConnection


router = Router()
BUSINESS_CONNECTIONS_FILE = Path("data/business_connections.json")


def _read_connections() -> dict[str, Any]:
    if not BUSINESS_CONNECTIONS_FILE.exists():
        return {"connections": {}}
    return json.loads(BUSINESS_CONNECTIONS_FILE.read_text(encoding="utf-8"))


def _write_connections(payload: dict[str, Any]) -> None:
    BUSINESS_CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUSINESS_CONNECTIONS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@router.business_connection()
async def handle_business_connection(connection: BusinessConnection) -> None:
    rights = connection.rights
    can_manage_stories = bool(getattr(rights, "can_manage_stories", False)) if rights else False
    payload = _read_connections()
    connections = payload.setdefault("connections", {})
    connections[str(connection.id)] = {
        "id": connection.id,
        "user_id": connection.user.id,
        "user_chat_id": connection.user_chat_id,
        "is_enabled": connection.is_enabled,
        "can_reply": connection.can_reply,
        "can_manage_stories": can_manage_stories,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_connections(payload)
    logging.info(
        "Business connection updated id=%s user_id=%s enabled=%s can_manage_stories=%s",
        connection.id,
        connection.user.id,
        connection.is_enabled,
        can_manage_stories,
    )
