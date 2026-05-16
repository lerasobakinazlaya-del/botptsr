from __future__ import annotations

from services.launch_service import build_start_parameter, build_deep_link, normalize_launch_slug


def build_content_calendar(launch_settings: dict) -> list[dict]:
    studio = launch_settings.get("content_studio") if isinstance(launch_settings.get("content_studio"), dict) else {}
    bot_username = str(launch_settings.get("bot_username") or "").strip().lstrip("@")
    default_source = str(launch_settings.get("default_source") or "telegram").strip()
    scripts = studio.get("video_scripts") if isinstance(studio.get("video_scripts"), list) else []
    items: list[dict] = []

    for index, script in enumerate(scripts, start=1):
        if not isinstance(script, dict):
            continue
        platform = normalize_launch_slug(script.get("platform") or default_source, fallback="telegram")
        campaign = normalize_launch_slug(script.get("campaign") or launch_settings.get("active_campaign"), fallback="launch")
        content = normalize_launch_slug(script.get("content") or f"script_{index}", fallback=f"script_{index}")
        start_parameter = build_start_parameter(
            source=platform,
            campaign=campaign,
            medium="video" if platform in {"tiktok", "instagram"} else "organic",
            content=content,
        )
        url = build_deep_link(bot_username, start_parameter)
        caption = str(script.get("caption") or "").strip().replace("{url}", url)
        items.append(
            {
                "day": index,
                "platform": platform,
                "campaign": campaign,
                "content": content,
                "title": str(script.get("title") or "").strip(),
                "shot_list": [str(item).strip() for item in script.get("shot_list", []) if str(item).strip()],
                "caption": caption,
                "start_parameter": start_parameter,
                "url": url,
            }
        )
    return items
