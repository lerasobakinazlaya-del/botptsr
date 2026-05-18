import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.content_campaign_service import build_campaign_items  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Выгрузить готовые подписи и Telegram-посты.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "content_campaigns.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "logs" / "caption_pack.md"))
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    items = build_campaign_items(config)
    lines = ["# Пакет подписей", ""]
    for item in items:
        lines.extend(
            [
                f"## {item.get('id') or item['content']}",
                "",
                f"Площадка: {item.get('platform')}",
                f"Стартовый параметр: `{item['start_parameter']}`",
                f"URL: {item['url'] or 'сначала укажи bot_username'}",
                "",
                "Подпись:",
                "",
                item.get("caption") or "",
                "",
                "Закреплённый комментарий:",
                "",
                f"Проверить бота: {item['url'] or 'сначала укажи bot_username'}",
                "",
            ]
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Пакет подписей сохранён: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
