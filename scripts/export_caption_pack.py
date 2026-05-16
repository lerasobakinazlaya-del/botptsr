import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.content_campaign_service import build_campaign_items  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export ready captions and Telegram posts.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "content_campaigns.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "logs" / "caption_pack.md"))
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    items = build_campaign_items(config)
    lines = ["# Caption Pack", ""]
    for item in items:
        lines.extend(
            [
                f"## {item.get('id') or item['content']}",
                "",
                f"Platform: {item.get('platform')}",
                f"Start parameter: `{item['start_parameter']}`",
                f"URL: {item['url'] or 'set bot_username first'}",
                "",
                "Caption:",
                "",
                item.get("caption") or "",
                "",
                "Pinned comment:",
                "",
                f"Проверить бота: {item['url'] or 'set bot_username first'}",
                "",
            ]
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Caption pack written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
