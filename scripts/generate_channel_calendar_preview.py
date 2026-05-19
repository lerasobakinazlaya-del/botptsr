from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Markdown preview for the channel post calendar.")
    parser.add_argument("--schedule-file", default="config/channel_schedule.json")
    parser.add_argument("--published-log", default="data/channel_published.json")
    parser.add_argument("--output", default="docs/channel-calendar-preview.md")
    parser.add_argument("--excerpt-chars", type=int, default=420)
    return parser.parse_args()


def read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def format_dt(value: str, timezone_name: str) -> str:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone_name))
    return dt.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M %Z")


def excerpt(path: Path, limit: int) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def main() -> None:
    args = parse_args()
    schedule = read_json(Path(args.schedule_file), {"items": []})
    published = read_json(Path(args.published_log), {"published": {}}).get("published", {})
    timezone_name = str(schedule.get("timezone") or "Europe/Moscow")

    lines = [
        "# Календарь постов канала",
        "",
        f"Канал: `{schedule.get('default_chat_id', '@trynit_ai')}`",
        f"Часовой пояс: `{timezone_name}`",
        "",
        "Статусы: `published` уже опубликован, `scheduled` стоит в очереди, `disabled` выключен.",
        "",
    ]

    items = sorted(schedule.get("items", []), key=lambda item: str(item.get("publish_at") or ""))
    for item in items:
        item_id = str(item.get("id") or "")
        is_published = item_id in published
        is_enabled = bool(item.get("enabled", True))
        status = "published" if is_published else "scheduled" if is_enabled else "disabled"
        text_file = Path(str(item.get("text_file") or ""))
        image_file = Path(str(item.get("image_file") or "")) if item.get("image_file") else None
        lines.extend(
            [
                f"## {format_dt(str(item.get('publish_at')), timezone_name)} · `{status}`",
                "",
                f"ID: `{item_id}`",
                f"Файл: `{text_file.as_posix()}`",
                f"Картинка: `{image_file.as_posix() if image_file else ''}`",
                f"Кнопка: `{item.get('button_text', '')}`",
                f"Ссылка: `{item.get('button_url', '')}`",
                f"Закреп: `{bool(item.get('pin', False))}`",
            ]
        )
        if is_published:
            lines.append(f"Telegram message_id: `{published[item_id].get('message_id')}`")
        lines.extend(["", "Предпросмотр:", "", "```text", excerpt(text_file, args.excerpt_chars), "```", ""])

    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    print(f"Calendar preview written: {args.output}")


if __name__ == "__main__":
    main()
