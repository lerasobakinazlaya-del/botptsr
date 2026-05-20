from __future__ import annotations

import argparse
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


START_PARAMETER_MAX_LENGTH = 64


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish due Telegram Stories for a Business account.")
    parser.add_argument("--schedule-file", default="config/story_schedule.json")
    parser.add_argument("--published-log", default="data/story_published.json")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--now", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--token-env", default="BOT_TOKEN")
    parser.add_argument("--business-env", default="")
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


def telegram_multipart_call(token: str, method: str, payload: dict, files: dict[str, Path]) -> dict:
    boundary = "----nit-story-boundary"
    chunks: list[bytes] = []
    for key, value in payload.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for key, path in files.items():
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{key}"; filename="{path.name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Telegram {method} failed: {error_body}") from exc


def build_story_payload(item: dict, business_connection_id: str, active_period: int, post_to_chat_page: bool) -> tuple[dict, dict[str, Path]]:
    image_path = Path(str(item.get("image_file") or ""))
    if not image_path.exists():
        raise FileNotFoundError(f"Story image not found: {image_path}")
    content = {
        "type": "photo",
        "photo": "attach://story_photo",
    }
    payload = {
        "business_connection_id": business_connection_id,
        "content": json.dumps(content, ensure_ascii=False),
        "active_period": int(item.get("active_period") or active_period),
        "caption": str(item.get("caption") or ""),
        "post_to_chat_page": "true" if bool(item.get("post_to_chat_page", post_to_chat_page)) else "false",
    }
    return payload, {"story_photo": image_path}


def validate_caption_links(item: dict) -> None:
    caption = str(item.get("caption") or "")
    marker = "?start="
    if marker not in caption:
        return
    start_parameter = caption.split(marker, 1)[1].split()[0].strip()
    if len(start_parameter) > START_PARAMETER_MAX_LENGTH:
        raise ValueError(
            f"{item.get('id')}: Telegram start parameter is too long: "
            f"{len(start_parameter)} > {START_PARAMETER_MAX_LENGTH}"
        )


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

    due_items: list[tuple[datetime, dict]] = []
    for item in schedule.get("items", []):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise SystemExit("Story schedule item without id.")
        if item_id in published:
            continue
        if not bool(item.get("enabled", True)):
            continue
        validate_caption_links(item)
        publish_at = parse_time(str(item.get("publish_at") or ""), default_tz)
        if publish_at <= now:
            due_items.append((publish_at, item))

    due_items.sort(key=lambda pair: pair[0])
    if args.limit > 0:
        due_items = due_items[: args.limit]

    print(f"Now UTC: {now.isoformat()}")
    print(f"Due stories: {len(due_items)}")
    for publish_at, item in due_items:
        print(f"- {item['id']} at {publish_at.isoformat()} image={item.get('image_file')}")

    if args.dry_run or not due_items:
        return

    token = os.getenv(args.token_env, "").strip()
    business_env = args.business_env or str(schedule.get("business_connection_env") or "TELEGRAM_BUSINESS_CONNECTION_ID")
    business_connection_id = os.getenv(business_env, "").strip()
    if not token:
        raise SystemExit(f"{args.token_env} is not set.")
    if not business_connection_id:
        print(f"{business_env} is not set. Stories were generated but not published.")
        return

    active_period = int(schedule.get("active_period") or 86400)
    post_to_chat_page = bool(schedule.get("post_to_chat_page", True))
    for publish_at, item in due_items:
        payload, files = build_story_payload(item, business_connection_id, active_period, post_to_chat_page)
        result = telegram_multipart_call(token, "postStory", payload, files)
        story_id = result.get("result", {}).get("id")
        print(f"Posted story {item['id']} story_id={story_id}")
        published[str(item["id"])] = {
            "story_id": story_id,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "scheduled_at": publish_at.isoformat(),
            "image_file": item.get("image_file", ""),
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "github_sha": os.getenv("GITHUB_SHA", ""),
        }
        write_json(published_path, published_log)


if __name__ == "__main__":
    main()
