import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.launch_service import build_launch_links  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate launch deep links from runtime settings.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "runtime_settings.json"))
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()

    payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    links = build_launch_links(payload.get("launch", {}))
    if args.format == "json":
        print(json.dumps({"items": links}, ensure_ascii=False, indent=2))
        return 0

    for item in links:
        print(f"### {item['name']}")
        print(f"- Канал: {item['source']} / {item['medium']}")
        print(f"- Кампания: {item['campaign']} / {item['content']}")
        print(f"- Link: {item['url']}")
        if item.get("caption"):
            print(f"- Caption: {item['caption']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
