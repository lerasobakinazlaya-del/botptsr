from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACTORY_ROOT = PROJECT_ROOT / "content-factory"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from render_short import render_short, resolve_message_path  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def export_meta_files() -> list[Path]:
    return sorted((FACTORY_ROOT / "exports").glob("*/*.json"))


def env_status(required: list[str]) -> tuple[str, list[str]]:
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        return "needs_credentials", missing
    return "ready_api", []


def build_publish_queue(platforms_config: dict[str, Any]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for meta_path in export_meta_files():
        meta = read_json(meta_path)
        platform = str(meta["platform"])
        platform_config = platforms_config.get(platform) or {}
        if not platform_config.get("enabled", True):
            status = "disabled"
            missing: list[str] = []
        else:
            status, missing = env_status([str(item) for item in platform_config.get("required_env") or []])
            if status == "needs_credentials" and platform_config.get("mode") == "api_or_manual":
                status = "ready_manual"
            if status == "ready_api" and platform != "telegram":
                status = "ready_api_not_uploaded"
        queue.append(
            {
                "id": meta["id"],
                "platform": platform,
                "status": status,
                "missing_env": missing,
                "video_file": meta["video_file"],
                "caption_file": meta["caption_file"],
                "cover_file": meta["cover_file"],
                "hook": meta["hook"],
                "mode": platform_config.get("mode", "manual"),
                "notes": platform_config.get("notes", ""),
            }
        )
    return queue


def write_queue_csv(queue: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "platform", "status", "missing_env", "video_file", "caption_file", "cover_file", "hook", "mode", "notes"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for item in queue:
            row = dict(item)
            row["missing_env"] = ",".join(row.get("missing_env") or [])
            writer.writerow(row)


def render_messages(messages: list[str]) -> None:
    for message in messages:
        message_path = resolve_message_path(message)
        exports = render_short(message_path)
        for export in exports:
            print(f"Exported {export.relative_to(PROJECT_ROOT).as_posix()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the standalone content factory pipeline.")
    parser.add_argument("--message", action="append", help="Message id/path to render. Can be passed multiple times.")
    parser.add_argument("--all", action="store_true", help="Render all JSON messages in content-factory/messages.")
    parser.add_argument("--skip-render", action="store_true", help="Only rebuild publication queue from existing exports.")
    args = parser.parse_args()

    messages = args.message or []
    if args.all:
        messages.extend(str(path) for path in sorted((FACTORY_ROOT / "messages").glob("*.json")))
    if not args.skip_render:
        if not messages:
            raise SystemExit("Pass --message night_001 or --all, or use --skip-render")
        render_messages(messages)

    platforms_config = read_json(FACTORY_ROOT / "config" / "platforms.json")
    queue = build_publish_queue(platforms_config)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": queue,
    }
    write_json(FACTORY_ROOT / "analytics" / "publish_queue.json", payload)
    write_queue_csv(queue, FACTORY_ROOT / "analytics" / "publish_queue.csv")
    print(f"Publish queue items: {len(queue)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
