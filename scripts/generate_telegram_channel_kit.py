import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.content_campaign_service import build_campaign_items  # noqa: E402
from services.launch_service import build_launch_links  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Сгенерировать пакет запуска Telegram-канала.")
    parser.add_argument("--runtime", default=str(PROJECT_ROOT / "config" / "runtime_settings.json"))
    parser.add_argument("--content", default=str(PROJECT_ROOT / "config" / "content_campaigns.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "logs" / "telegram_channel_kit.md"))
    args = parser.parse_args()

    runtime = json.loads(Path(args.runtime).read_text(encoding="utf-8"))
    content = json.loads(Path(args.content).read_text(encoding="utf-8"))
    launch = runtime.get("launch", {})
    studio = launch.get("content_studio", {})
    channel = studio.get("telegram_channel", {})
    links = build_launch_links(launch)
    content_items = build_campaign_items(content)
    telegram_items = [item for item in content_items if item.get("platform") == "telegram"]
    telegram_link = next((item for item in links if item.get("source") == "telegram"), {})
    url = telegram_link.get("url") or "сначала укажи launch.bot_username"
    pinned = str(channel.get("pinned_post_template") or "").replace("{url}", url)

    lines = [
        "# Пакет запуска Telegram-канала",
        "",
        f"Название: {channel.get('title') or 'Нить: AI-собеседник'}",
        f"Юзернейм канала: @{channel.get('handle') or 'укажи_юзернейм'}",
        "",
        "Описание:",
        "",
        channel.get("description") or "",
        "",
        "Закреплённый пост:",
        "",
        pinned,
        "",
        "Стартовая ссылка:",
        "",
        url,
        "",
        "Первые посты:",
        "",
    ]
    for item in telegram_items:
        lines.extend(
            [
                f"## {item.get('title') or item.get('id')}",
                "",
                item.get("caption") or "",
                "",
                f"Трекинг: `{item.get('start_parameter')}`",
                "",
            ]
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Пакет Telegram-канала сохранён: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
