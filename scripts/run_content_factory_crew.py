from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run_step(name: str, command: list[str]) -> None:
    print(f"\n== {name} ==")
    print(" ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_upload_queue(board_path: Path, output_path: Path) -> None:
    rows = read_csv(board_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ready_for_upload",
        "mode": "manual_or_api",
        "note": "Один MP4 можно загрузить в TikTok, Reels и Shorts. Автозалив включается после OAuth/API-доступов; до этого это рабочая очередь для ручной загрузки.",
        "items": [
            {
                "platform": row.get("platform", ""),
                "id": row.get("id", ""),
                "publish_time": row.get("publish_time", ""),
                "video_file": row.get("video_file", ""),
                "caption": row.get("caption", ""),
                "tracking_url": row.get("url", ""),
                "status": "ready_manual",
            }
            for row in rows
        ],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Очередь загрузки TikTok / Reels / Shorts",
        "",
        "Это список готовых роликов на сегодня. Автозагрузка включается после подключения API-токенов и прохождения review у платформ; пока очередь можно использовать для ручной публикации без потери трекинга.",
        "",
    ]
    for item in payload["items"]:
        lines.extend(
            [
                f"## {item['publish_time']} · {item['platform']} · `{item['id']}`",
                "",
                f"Видео: `{item['video_file']}`",
                f"Ссылка: `{item['tracking_url']}`",
                "",
                "```text",
                item["caption"],
                "```",
                "",
            ]
        )
    (PROJECT_ROOT / "docs" / "social-upload-queue.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Nit content factory crew for one production day.")
    parser.add_argument("--start-date", default=date.today().isoformat())
    parser.add_argument("--day", type=int, default=1, help="Campaign day to render into social exports.")
    parser.add_argument("--skip-render", action="store_true", help="Only rebuild plans/queues without rendering media.")
    args = parser.parse_args()

    start = date.fromisoformat(args.start_date)
    run_step("showrunner + copywriter: generate 7-day plan", [PYTHON, "scripts/generate_growth_content_plan.py", "--start-date", start.isoformat()])

    if not args.skip_render:
        run_step("story producer: render Telegram story videos", [PYTHON, "scripts/generate_story_assets.py"])
        run_step("designer: render 49 message cards", [PYTHON, "scripts/generate_message_card_pack.py"])
        run_step("video editor + sound designer: render daily short videos", [PYTHON, "scripts/generate_social_videos.py", "--day", str(args.day)])

    run_step("publisher: update channel calendar preview", [PYTHON, "scripts/generate_channel_calendar_preview.py"])
    run_step("analyst: rank social hooks", [PYTHON, "scripts/analyze_social_metrics.py"])
    write_upload_queue(PROJECT_ROOT / "docs" / "social-video-board-current.csv", PROJECT_ROOT / "content-factory" / "analytics" / "social_upload_queue.json")
    print(f"\nReady: content day {args.day}, window {start.isoformat()} - {(start + timedelta(days=6)).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
