from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
START_PARAMETER_MAX_LENGTH = 64


def read_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_start_parameter(item: dict[str, Any]) -> str:
    source = str(item.get("source") or item.get("platform") or "telegram").strip().lower()
    campaign = str(item.get("campaign") or "growth").strip().lower()
    medium = str(item.get("medium") or "organic").strip().lower()
    content = str(item.get("content") or item.get("id") or "creative").strip().lower()
    return f"src_{source}__cmp_{campaign}__med_{medium}__cnt_{content}"


def build_url(bot_username: str, start_parameter: str) -> str:
    username = bot_username.strip().lstrip("@")
    if not username:
        return ""
    return f"https://t.me/{username}?start={start_parameter}"


def render_markdown(config: dict[str, Any]) -> str:
    bot_username = str(config.get("bot_username") or "")
    items = sorted(config.get("items") or [], key=lambda item: (int(item.get("day") or 0), str(item.get("id") or "")))
    lines: list[str] = [
        "# Video production board",
        "",
        f"Кампания: `{config.get('campaign', '')}`",
        f"Бот: `@{bot_username.strip().lstrip('@')}`",
        "",
        "## Как пользоваться",
        "",
        "1. Берём ролики со статусом `ready_for_edit` первыми.",
        "2. Исходники складываем в `assets/videos/sources/<id>/`.",
        "3. Финальный MP4 складываем в `assets/videos/renders/<id>.mp4`.",
        "4. После публикации заносим ссылку и метрики в таблицу роста.",
        "",
    ]

    for item in items:
        start_parameter = build_start_parameter(item)
        if len(start_parameter) > START_PARAMETER_MAX_LENGTH:
            raise ValueError(f"{item.get('id')}: start parameter is too long: {len(start_parameter)} > {START_PARAMETER_MAX_LENGTH}")
        url = build_url(bot_username, start_parameter)
        caption = str(item.get("caption") or "").replace("{url}", url)
        item_id = str(item.get("id") or item.get("content") or "creative")

        lines.extend(
            [
                f"## Day {item.get('day', '')}: {item_id}",
                "",
                f"Статус: `{item.get('status', '')}`",
                f"Площадка: `{item.get('platform', '')}`",
                f"Рубрика: `{item.get('pillar', '')}`",
                f"Длина: `{item.get('duration_sec', '')} sec`",
                f"Формат ассетов: `{item.get('asset_plan', '')}`",
                f"Start parameter: `{start_parameter}`",
                f"URL: `{url}`",
                "",
                f"Хук: {item.get('hook', '')}",
                f"Название: {item.get('title', '')}",
                "",
                "Сцены:",
            ]
        )
        for scene in item.get("scenes") or []:
            lines.append(f"- {scene}")

        lines.extend(["", "Исходники:"])
        for asset in item.get("source_assets") or []:
            lines.append(f"- `{asset}`")

        lines.extend(
            [
                "",
                "Подпись:",
                "",
                "```text",
                caption,
                "```",
                "",
                f"CTA: {item.get('cta', '')}",
                f"Модерация: {item.get('safety_notes', '')}",
                "",
            ]
        )

    return "\n".join(lines)


def write_csv(config: dict[str, Any], output: Path) -> None:
    bot_username = str(config.get("bot_username") or "")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "day",
                "id",
                "status",
                "platform",
                "pillar",
                "hook",
                "start_parameter",
                "url",
                "render_path",
                "published_url",
                "views",
                "bot_starts",
                "paid_users",
                "notes",
            ],
        )
        writer.writeheader()
        for item in sorted(config.get("items") or [], key=lambda row: (int(row.get("day") or 0), str(row.get("id") or ""))):
            start_parameter = build_start_parameter(item)
            if len(start_parameter) > START_PARAMETER_MAX_LENGTH:
                raise ValueError(
                    f"{item.get('id')}: start parameter is too long: "
                    f"{len(start_parameter)} > {START_PARAMETER_MAX_LENGTH}"
                )
            item_id = str(item.get("id") or item.get("content") or "creative")
            writer.writerow(
                {
                    "day": item.get("day", ""),
                    "id": item_id,
                    "status": item.get("status", ""),
                    "platform": item.get("platform", ""),
                    "pillar": item.get("pillar", ""),
                    "hook": item.get("hook", ""),
                    "start_parameter": start_parameter,
                    "url": build_url(bot_username, start_parameter),
                    "render_path": f"assets/videos/renders/{item_id}.mp4",
                    "published_url": "",
                    "views": "",
                    "bot_starts": "",
                    "paid_users": "",
                    "notes": "",
                }
            )


def ensure_video_dirs(config: dict[str, Any]) -> None:
    production_root = PROJECT_ROOT / str(config.get("production_root") or "assets/videos")
    for directory in ("briefs", "renders", "sources"):
        (production_root / directory).mkdir(parents=True, exist_ok=True)
    for item in config.get("items") or []:
        item_id = str(item.get("id") or item.get("content") or "creative")
        (production_root / "sources" / item_id).mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SaaS video briefs and a production board.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "video_pipeline.json"))
    parser.add_argument("--markdown", default=str(PROJECT_ROOT / "docs" / "video-briefs.md"))
    parser.add_argument("--csv", default=str(PROJECT_ROOT / "docs" / "video-production-board.csv"))
    args = parser.parse_args()

    config = read_config(Path(args.config))
    ensure_video_dirs(config)

    markdown_path = Path(args.markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(config), encoding="utf-8-sig")

    write_csv(config, Path(args.csv))
    print(f"Video briefs written: {markdown_path}")
    print(f"Production board written: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
