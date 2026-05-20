from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from publish_telegram_channel_post import telegram_call, telegram_multipart_call


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish due Telegram channel posts from a schedule.")
    parser.add_argument("--schedule-file", default="config/channel_schedule.json")
    parser.add_argument("--published-log", default="data/channel_published.json")
    parser.add_argument("--limit", type=int, default=2, help="Max posts per run.")
    parser.add_argument(
        "--max-lag-hours",
        type=float,
        default=6,
        help="Skip posts that are older than this many hours. Use 0 to publish all backlog.",
    )
    parser.add_argument("--now", default="", help="Override current time as ISO timestamp.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--token-env", default="BOT_TOKEN")
    return parser.parse_args()


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_time(value: str, default_tz: ZoneInfo) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Empty datetime")
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(timezone.utc)


def build_message_payload(item: dict, schedule: dict) -> dict:
    text_file = Path(str(item["text_file"]))
    text = text_file.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Text file is empty: {text_file}")

    payload = {
        "chat_id": item.get("chat_id") or schedule.get("default_chat_id") or "@trynit_ai",
        "text": text,
        "disable_web_page_preview": bool(item.get("disable_web_preview", False)),
    }
    button_text = str(item.get("button_text") or "").strip()
    button_url = str(item.get("button_url") or "").strip()
    if button_text and button_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": button_text, "url": button_url}]],
        }
    return payload


def publish_image_if_needed(token: str, item: dict, chat_id: str) -> int | None:
    image_file = str(item.get("image_file") or "").strip()
    if not image_file:
        return None
    image_path = Path(image_file)
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    result = telegram_multipart_call(
        token,
        "sendPhoto",
        {"chat_id": chat_id},
        {"photo": image_path},
    )
    return int(result["result"]["message_id"])


def publish_photo_with_caption_if_possible(token: str, item: dict, payload: dict) -> int | None:
    image_file = str(item.get("image_file") or "").strip()
    if not image_file:
        return None
    text = str(payload.get("text") or "")
    if len(text) > 1024:
        return None
    image_path = Path(image_file)
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    photo_payload = {
        "chat_id": payload["chat_id"],
        "caption": text,
    }
    if payload.get("reply_markup"):
        photo_payload["reply_markup"] = payload["reply_markup"]
    result = telegram_multipart_call(token, "sendPhoto", photo_payload, {"photo": image_path})
    return int(result["result"]["message_id"])


def main() -> None:
    args = parse_args()
    load_dotenv(".env")

    schedule_path = Path(args.schedule_file)
    published_path = Path(args.published_log)
    schedule = read_json(schedule_path, {"items": []})
    published_log = read_json(published_path, {"published": {}})
    published = published_log.setdefault("published", {})

    timezone_name = str(schedule.get("timezone") or "Europe/Moscow")
    default_tz = ZoneInfo(timezone_name)
    now = parse_time(args.now, default_tz) if args.now else datetime.now(timezone.utc)

    due_items = []
    for item in schedule.get("items", []):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise SystemExit("Schedule item without id.")
        if item_id in published:
            continue
        if not bool(item.get("enabled", True)):
            continue
        publish_at = parse_time(str(item.get("publish_at") or ""), default_tz)
        if publish_at <= now:
            if args.max_lag_hours > 0:
                lag_hours = (now - publish_at).total_seconds() / 3600
                if lag_hours > args.max_lag_hours:
                    print(f"Skipping stale post {item_id}: lag_hours={lag_hours:.2f}")
                    if args.dry_run:
                        continue
                    published[str(item_id)] = {
                        "skipped": True,
                        "reason": "stale",
                        "skipped_at": datetime.now(timezone.utc).isoformat(),
                        "scheduled_at": publish_at.isoformat(),
                        "text_file": item.get("text_file", ""),
                        "image_file": item.get("image_file", ""),
                    }
                    write_json(published_path, published_log)
                    continue
            due_items.append((publish_at, item))

    due_items.sort(key=lambda pair: pair[0])
    if args.limit > 0:
        due_items = due_items[: args.limit]

    print(f"Now UTC: {now.isoformat()}")
    print(f"Due posts: {len(due_items)}")
    for publish_at, item in due_items:
        image_note = f" image={item.get('image_file')}" if item.get("image_file") else ""
        print(f"- {item['id']} at {publish_at.isoformat()} file={item['text_file']}{image_note}")

    if args.dry_run or not due_items:
        return

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"{args.token_env} is not set.")

    for publish_at, item in due_items:
        payload = build_message_payload(item, schedule)
        photo_message_id = publish_photo_with_caption_if_possible(token, item, payload)
        if photo_message_id:
            message_id = photo_message_id
            print(f"Posted {item['id']} as photo post message_id={message_id}")
        else:
            photo_message_id = publish_image_if_needed(token, item, str(payload["chat_id"]))
            if photo_message_id:
                print(f"Posted image for {item['id']} photo_message_id={photo_message_id}")

            result = telegram_call(token, "sendMessage", payload)
            message_id = int(result["result"]["message_id"])
            print(f"Posted {item['id']} message_id={message_id}")

        if bool(item.get("pin", False)):
            telegram_call(
                token,
                "pinChatMessage",
                {
                    "chat_id": payload["chat_id"],
                    "message_id": message_id,
                    "disable_notification": True,
                },
            )
            print(f"Pinned {item['id']} message_id={message_id}")

        published[str(item["id"])] = {
            "message_id": message_id,
            "photo_message_id": photo_message_id,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "scheduled_at": publish_at.isoformat(),
            "text_file": item["text_file"],
            "image_file": item.get("image_file", ""),
            "chat_id": payload["chat_id"],
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "github_sha": os.getenv("GITHUB_SHA", ""),
        }
        write_json(published_path, published_log)


if __name__ == "__main__":
    main()
