import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.content_campaign_service import validate_campaign_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверить конфиг SMM-контент-кампаний.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "content_campaigns.json"))
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    errors = validate_campaign_config(config)
    if errors:
        print("Проверка контент-пайплайна не прошла:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Проверка контент-пайплайна прошла.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
