from __future__ import annotations

from typing import Any

from services.launch_service import build_deep_link, build_start_parameter, normalize_launch_slug


START_PARAMETER_MAX_LENGTH = 64


def build_campaign_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    bot_username = str(config.get("bot_username") or "").strip().lstrip("@")
    default_campaign = normalize_launch_slug(config.get("campaign") or "launch", fallback="launch")
    items = config.get("items") if isinstance(config.get("items"), list) else []
    prepared: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        source = normalize_launch_slug(item.get("source") or item.get("platform") or "telegram", fallback="telegram")
        campaign = normalize_launch_slug(item.get("campaign") or default_campaign, fallback=default_campaign)
        medium = normalize_launch_slug(item.get("medium") or "organic", fallback="organic")
        content = normalize_launch_slug(item.get("content") or item.get("id") or f"content_{index}", fallback=f"content_{index}")
        start_parameter = build_start_parameter(
            source=source,
            campaign=campaign,
            medium=medium,
            content=content,
        )
        url = build_deep_link(bot_username, start_parameter)
        caption = str(item.get("caption") or "").strip().replace("{url}", url)
        prepared.append(
            {
                **item,
                "source": source,
                "campaign": campaign,
                "medium": medium,
                "content": content,
                "start_parameter": start_parameter,
                "url": url,
                "caption": caption,
                "day": int(item.get("day") or index),
            }
        )
    return prepared


def validate_campaign_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    items = build_campaign_items(config)
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("id") or item.get("content") or "unknown")
        start_parameter = str(item.get("start_parameter") or "")
        if not item.get("platform"):
            errors.append(f"{item_id}: укажи площадку platform")
        if not item.get("hook"):
            errors.append(f"{item_id}: укажи крючок hook")
        if not item.get("caption"):
            errors.append(f"{item_id}: укажи подпись caption")
        if not item.get("safe_copy_checked"):
            errors.append(f"{item_id}: safe_copy_checked должен быть true")
        if len(start_parameter) > START_PARAMETER_MAX_LENGTH:
            errors.append(f"{item_id}: start_parameter слишком длинный ({len(start_parameter)} > {START_PARAMETER_MAX_LENGTH})")
        if start_parameter in seen:
            errors.append(f"{item_id}: повторяется start_parameter {start_parameter}")
        seen.add(start_parameter)
    if not items:
        errors.append("Не найдены элементы контент-кампании")
    return errors
