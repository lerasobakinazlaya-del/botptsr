from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from publish_telegram_channel_post import telegram_multipart_call


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send generated stories to admins for manual channel publishing.")
    parser.add_argument("--schedule-file", default="config/story_schedule.json")
    parser.add_argument("--delivered-log", default="data/story_delivered.json")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--now", default="")
    parser.add_argument("--all", action="store_true", help="Send next undelivered stories regardless of schedule time.")
    parser.add_argument("--force", action="store_true", help="Ignore delivery log and resend matching stories.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--token-env", default="BOT_TOKEN")
    parser.add_argument("--chat-env", default="")
    return parser.parse_args()


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_time(value: str, default_tz: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(timezone.utc)


def resolve_delivery_chat_ids(schedule: dict, chat_env: str) -> list[str]:
    env_name = chat_env or str(schedule.get("delivery_chat_env") or "STORY_DELIVERY_CHAT_ID")
    raw = os.getenv(env_name, "").strip()
    if not raw:
        fallback_env = str(schedule.get("delivery_fallback") or "OWNER_ID")
        raw = os.getenv(fallback_env, "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_caption(item: dict) -> str:
    bubble_text = str(item.get("bubble_text") or "").strip()
    return (
        "Готовое видео-сторис для канала.\n\n"
        f"ID: {item.get('id')}\n\n"
        "Текст на видео:\n"
        f"{bubble_text}\n\n"
        "Как публиковать:\n"
        "1. Выложи это видео в сторис канала.\n"
        "2. Добавь стикер-ссылку или упоминание @asknitai_bot.\n"
        "3. Короткий CTA: «Попробовать Нить»."
    )[:1024]


def story_media_path(item: dict) -> Path:
    media_value = str(item.get("video_file") or item.get("image_file") or "").strip()
    if not media_value:
        raise FileNotFoundError(f"Story media is not configured for {item.get('id')}")
    media_path = Path(media_value)
    if not media_path.exists():
        raise FileNotFoundError(f"Story media not found: {media_path}")
    return media_path


def telegram_media_method(media_path: Path) -> tuple[str, str]:
    if media_path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        return "sendVideo", "video"
    return "sendPhoto", "photo"


def main() -> None:
    args = parse_args()
    load_dotenv(".env")

    schedule_path = Path(args.schedule_file)
    delivered_path = Path(args.delivered_log)
    schedule = read_json(schedule_path, {"items": []})
    delivered_log = read_json(delivered_path, {"delivered": {}})
    delivered = delivered_log.setdefault("delivered", {})

    timezone_name = str(schedule.get("timezone") or "Europe/Moscow")
    default_tz = ZoneInfo(timezone_name)
    now = parse_time(args.now, default_tz) if args.now else datetime.now(timezone.utc)

    due_items: list[tuple[datetime, dict]] = []
    for item in schedule.get("items", []):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise SystemExit("Story schedule item without id.")
        if not args.force and item_id in delivered:
            continue
        if not bool(item.get("enabled", True)):
            continue
        publish_at = parse_time(str(item.get("publish_at") or ""), default_tz)
        if args.all or publish_at <= now:
            due_items.append((publish_at, item))

    due_items.sort(key=lambda pair: pair[0])
    if args.limit > 0:
        due_items = due_items[: args.limit]

    print(f"Now UTC: {now.isoformat()}")
    print(f"Story deliveries selected: {len(due_items)}")
    for publish_at, item in due_items:
        print(f"- {item['id']} at {publish_at.isoformat()} media={item.get('video_file') or item.get('image_file')}")

    if args.dry_run or not due_items:
        return

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"{args.token_env} is not set.")

    chat_ids = resolve_delivery_chat_ids(schedule, args.chat_env)
    if not chat_ids:
        raise SystemExit("No story delivery chat id found. Set STORY_DELIVERY_CHAT_ID or OWNER_ID.")

    for publish_at, item in due_items:
        media_path = story_media_path(item)
        method, file_key = telegram_media_method(media_path)

        message_ids: dict[str, int] = {}
        for chat_id in chat_ids:
            result = telegram_multipart_call(
                token,
                method,
                {"chat_id": chat_id, "caption": build_caption(item), "supports_streaming": "true"},
                {file_key: media_path},
            )
            message_id = int(result["result"]["message_id"])
            message_ids[chat_id] = message_id
            print(f"Delivered {item['id']} to chat_id={chat_id} message_id={message_id}")

        delivered[str(item["id"])] = {
            "delivered_at": datetime.now(timezone.utc).isoformat(),
            "scheduled_at": publish_at.isoformat(),
            "image_file": item.get("image_file", ""),
            "video_file": item.get("video_file", ""),
            "message_ids": message_ids,
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "github_sha": os.getenv("GITHUB_SHA", ""),
        }
        write_json(delivered_path, delivered_log)


if __name__ == "__main__":
    main()
