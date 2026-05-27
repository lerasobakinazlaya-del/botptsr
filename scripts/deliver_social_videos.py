from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
from collections import defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOARD = PROJECT_ROOT / "docs" / "social-video-board-current.csv"
DEFAULT_QUEUE = PROJECT_ROOT / "content-factory" / "analytics" / "delivery_queue.json"
DEFAULT_LOG = PROJECT_ROOT / "data" / "social_video_delivered.json"
BOT_SHORT_URL = "https://t.me/asknitai_bot"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send ready TikTok/Reels/Shorts videos to an operator in Telegram.")
    parser.add_argument("--board", default=str(DEFAULT_BOARD))
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE), help="Production JSON queue. Used when it has items.")
    parser.add_argument("--delivered-log", default=str(DEFAULT_LOG))
    parser.add_argument("--limit", type=int, default=9, help="Max unique videos to send.")
    parser.add_argument("--all", action="store_true", help="Send the next undelivered videos regardless of publish time.")
    parser.add_argument("--force", action="store_true", help="Ignore delivery log and resend matching videos.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now", default="")
    parser.add_argument("--token-env", default="BOT_TOKEN")
    parser.add_argument("--chat-env", default="SOCIAL_DELIVERY_CHAT_ID")
    return parser.parse_args()


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_board(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def publish_time_from_item(item: dict) -> str:
    value = str(item.get("publish_time") or "").strip()
    if value:
        return value
    publish_at = str(item.get("publish_at") or "").strip()
    if "T" in publish_at:
        return publish_at.split("T", 1)[1][:5]
    return "00:00"


def read_queue(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    payload = read_json(path, {"items": []})
    rows: list[dict[str, str]] = []
    for item in payload.get("items") or []:
        rows.append(
            {
                "day": "",
                "publish_time": publish_time_from_item(item),
                "platform": str(item.get("platform") or ""),
                "id": str(item.get("id") or ""),
                "status": str(item.get("status") or "ready_manual"),
                "video_file": str(item.get("video_file") or ""),
                "caption": str(item.get("caption") or ""),
                "url": BOT_SHORT_URL,
            }
        )
    return rows


def parse_publish_time(value: str) -> time:
    hour, minute = str(value).strip().split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def resolve_delivery_chat_ids(chat_env: str) -> list[str]:
    for env_name in (chat_env, "SOCIAL_DELIVERY_CHAT_ID", "STORY_DELIVERY_CHAT_ID", "OWNER_ID"):
        raw = os.getenv(env_name, "").strip()
        if raw:
            return [item.strip() for item in raw.split(",") if item.strip()]
    return []


def telegram_json_call(token: str, method: str, payload: dict) -> dict:
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Telegram {method} failed: {body}") from exc


def telegram_multipart_call(token: str, method: str, payload: dict, files: dict[str, Path]) -> dict:
    boundary = "----nit-social-delivery"
    chunks: list[bytes] = []
    for key, value in payload.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for key, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{key}"; filename="{path.name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
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
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Telegram {method} failed: {body}") from exc


def compact_caption(video_id: str, rows: list[dict[str, str]]) -> str:
    platforms = ", ".join(row["platform"] for row in rows)
    publish_times = sorted({row["publish_time"] for row in rows if row.get("publish_time")})
    time_label = publish_times[0] if publish_times else "сегодня"
    return (
        "Готовый ролик для ручной публикации.\n\n"
        f"ID: {video_id}\n"
        f"Площадки: {platforms}\n"
        f"Время: {time_label}\n\n"
        "Следующим сообщением пришлю короткие тексты для вставки."
    )[:1024]


def public_link_for(platform: str) -> str:
    if platform in {"TikTok", "tiktok"}:
        return "ссылка на бота в профиле"
    return BOT_SHORT_URL


def details_text(video_id: str, rows: list[dict[str, str]]) -> str:
    lines = [
        f"Публикация: {video_id}",
        "",
        "Для вставки используй короткий вариант ниже. Длинный tracking хранится только в CSV для аналитики.",
        "",
    ]
    for row in rows:
        platform = row["platform"]
        lines.extend(
            [
                f"{platform} · {row['publish_time']}",
                f"Текст: {row['caption']}",
                f"Ссылка для вставки: {public_link_for(platform)}",
                "",
            ]
        )
    return "\n".join(lines)[:4096]


def unique_video_groups(rows: list[dict[str, str]]) -> list[tuple[str, Path, list[dict[str, str]]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        video_file = str(row.get("video_file") or "").strip()
        if video_file:
            grouped[video_file].append(row)

    groups: list[tuple[str, Path, list[dict[str, str]]]] = []
    for video_file, video_rows in grouped.items():
        video_path = PROJECT_ROOT / video_file
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        video_id = Path(video_file).stem
        video_rows.sort(key=lambda row: (row.get("publish_time", ""), row.get("platform", "")))
        groups.append((video_id, video_path, video_rows))

    groups.sort(key=lambda group: (group[2][0].get("day", ""), group[2][0].get("publish_time", ""), group[0]))
    return groups


def main() -> None:
    args = parse_args()
    load_dotenv(".env")

    board_path = Path(args.board)
    delivered_path = Path(args.delivered_log)
    delivered_log = read_json(delivered_path, {"delivered": {}})
    delivered = delivered_log.setdefault("delivered", {})

    tz = ZoneInfo("Europe/Moscow")
    now = datetime.fromisoformat(args.now).astimezone(tz) if args.now else datetime.now(tz)
    queue_path = Path(args.queue)
    rows = read_queue(queue_path) if queue_path.exists() else read_board(board_path)
    groups = unique_video_groups(rows)

    selected: list[tuple[str, Path, list[dict[str, str]]]] = []
    for video_id, video_path, video_rows in groups:
        if not args.force and video_id in delivered:
            continue
        first_time = parse_publish_time(video_rows[0].get("publish_time", "23:59"))
        if not args.all and first_time > now.time():
            continue
        selected.append((video_id, video_path, video_rows))
        if args.limit > 0 and len(selected) >= args.limit:
            break

    print(f"Now MSK: {now.isoformat()}")
    print(f"Selected social videos: {len(selected)}")
    for video_id, video_path, video_rows in selected:
        platforms = ", ".join(row["platform"] for row in video_rows)
        print(f"- {video_id}: {video_path.relative_to(PROJECT_ROOT).as_posix()} -> {platforms}")

    if args.dry_run or not selected:
        return

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"{args.token_env} is not set.")

    chat_ids = resolve_delivery_chat_ids(args.chat_env)
    if not chat_ids:
        raise SystemExit("No delivery chat id found. Set SOCIAL_DELIVERY_CHAT_ID, STORY_DELIVERY_CHAT_ID or OWNER_ID.")

    for video_id, video_path, video_rows in selected:
        message_ids: dict[str, list[int]] = {}
        for chat_id in chat_ids:
            video_result = telegram_multipart_call(
                token,
                "sendVideo",
                {"chat_id": chat_id, "caption": compact_caption(video_id, video_rows), "supports_streaming": "true"},
                {"video": video_path},
            )
            text_result = telegram_json_call(
                token,
                "sendMessage",
                {"chat_id": chat_id, "text": details_text(video_id, video_rows), "disable_web_page_preview": True},
            )
            message_ids[chat_id] = [
                int(video_result["result"]["message_id"]),
                int(text_result["result"]["message_id"]),
            ]
            print(f"Delivered {video_id} to chat_id={chat_id}")

        delivered[video_id] = {
            "delivered_at": datetime.now(timezone.utc).isoformat(),
            "video_file": video_path.relative_to(PROJECT_ROOT).as_posix(),
            "platform_ids": [row.get("id", "") for row in video_rows],
            "message_ids": message_ids,
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "github_sha": os.getenv("GITHUB_SHA", ""),
        }
        write_json(delivered_path, delivered_log)


if __name__ == "__main__":
    main()
