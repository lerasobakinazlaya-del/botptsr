import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.content_campaign_service import build_campaign_items  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SMM content calendar from content campaign config.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "content_campaigns.json"))
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    items = build_campaign_items(config)
    if args.format == "json":
        print(json.dumps({"items": items}, ensure_ascii=False, indent=2))
        return 0

    for item in items:
        print(f"## Day {item['day']}: {item.get('title') or item['content']}")
        print(f"- Platform: {item.get('platform')}")
        print(f"- Pillar: {item.get('pillar')}")
        print(f"- Start: {item['start_parameter']}")
        print(f"- URL: {item['url'] or 'set bot_username first'}")
        print(f"- Hook: {item.get('hook')}")
        print("- Shots:")
        for shot in item.get("shot_list") or []:
            print(f"  - {shot}")
        print(f"- Caption: {item.get('caption')}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
