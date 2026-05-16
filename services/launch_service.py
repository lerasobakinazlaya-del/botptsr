from __future__ import annotations

import re
from urllib.parse import quote


_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def normalize_launch_slug(value: str, *, fallback: str = "default") -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _SLUG_RE.sub("_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or fallback


def build_start_parameter(
    *,
    source: str,
    campaign: str,
    medium: str = "",
    content: str = "",
) -> str:
    parts = [
        f"src_{normalize_launch_slug(source, fallback='direct')}",
        f"cmp_{normalize_launch_slug(campaign, fallback='launch')}",
    ]
    if str(medium or "").strip():
        parts.append(f"med_{normalize_launch_slug(medium)}")
    if str(content or "").strip():
        parts.append(f"cnt_{normalize_launch_slug(content)}")
    return "__".join(parts)


def build_deep_link(bot_username: str, start_parameter: str) -> str:
    username = str(bot_username or "").strip().lstrip("@")
    if not username:
        return ""
    return f"https://t.me/{username}?start={quote(str(start_parameter or '').strip())}"


def build_launch_links(launch_settings: dict) -> list[dict]:
    bot_username = str(launch_settings.get("bot_username") or "").strip().lstrip("@")
    default_source = str(launch_settings.get("default_source") or "telegram").strip()
    campaigns = launch_settings.get("campaigns") or []
    if not isinstance(campaigns, list):
        campaigns = []

    links: list[dict] = []
    for item in campaigns:
        if not isinstance(item, dict) or not bool(item.get("enabled", True)):
            continue
        source = str(item.get("source") or default_source).strip()
        campaign = str(item.get("campaign") or item.get("name") or "").strip()
        if not campaign:
            continue
        medium = str(item.get("medium") or "").strip()
        content = str(item.get("content") or "").strip()
        start_parameter = build_start_parameter(
            source=source,
            campaign=campaign,
            medium=medium,
            content=content,
        )
        url = build_deep_link(bot_username, start_parameter)
        caption = str(item.get("caption") or launch_settings.get("default_caption") or "").strip()
        if "{url}" in caption:
            caption = caption.replace("{url}", url)
        links.append(
            {
                "name": str(item.get("name") or campaign).strip(),
                "source": normalize_launch_slug(source, fallback="direct"),
                "campaign": normalize_launch_slug(campaign, fallback="launch"),
                "medium": normalize_launch_slug(medium, fallback="") if medium else "",
                "content": normalize_launch_slug(content, fallback="") if content else "",
                "start_parameter": start_parameter,
                "url": url,
                "caption": caption,
            }
        )
    return links
