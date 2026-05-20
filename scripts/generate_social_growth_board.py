from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a daily social growth board for Shorts/Reels/TikTok.")
    parser.add_argument("--accounts", default=str(PROJECT_ROOT / "config" / "social_accounts.json"))
    parser.add_argument("--video-pipeline", default=str(PROJECT_ROOT / "config" / "video_pipeline.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "docs" / "social-growth-board.md"))
    args = parser.parse_args()

    accounts = read_json(Path(args.accounts))
    pipeline = read_json(Path(args.video_pipeline))
    targets = accounts.get("daily_targets", {})
    minimum = targets.get("minimum", {})
    scale = targets.get("scale_when_winning", {})
    items = sorted(pipeline.get("items") or [], key=lambda item: (int(item.get("day") or 0), str(item.get("id") or "")))

    lines = [
        "# Social growth board",
        "",
        f"Бренд: `{accounts.get('brand', {}).get('name', 'Нить')}`",
        f"Кампания: `{pipeline.get('campaign', '')}`",
        "",
        "## Daily targets",
        "",
        "| Platform | Minimum | Scale when winning |",
        "| --- | ---: | ---: |",
    ]
    for platform in ("tiktok", "instagram", "youtube"):
        lines.append(f"| {platform} | {minimum.get(platform, 0)} | {scale.get(platform, 0)} |")

    lines.extend(
        [
            "",
            "## Account setup",
            "",
            "| Platform | Status | Automation | Profile link |",
            "| --- | --- | --- | --- |",
        ]
    )
    for account in accounts.get("accounts") or []:
        lines.append(
            "| {platform} | {status} | {automation} | {link} |".format(
                platform=account.get("platform", ""),
                status=account.get("status", ""),
                automation=account.get("automation_mode", ""),
                link=account.get("profile_link", ""),
            )
        )

    lines.extend(
        [
            "",
            "## Production queue",
            "",
            "| Day | ID | Platform | Status | Hook | CTA |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for item in items:
        lines.append(
            "| {day} | `{id}` | {platform} | `{status}` | {hook} | {cta} |".format(
                day=item.get("day", ""),
                id=item.get("id", ""),
                platform=item.get("platform", ""),
                status=item.get("status", ""),
                hook=str(item.get("hook", "")).replace("|", "/"),
                cta=str(item.get("cta", "")).replace("|", "/"),
            )
        )

    lines.extend(
        [
            "",
            "## Evening decision rule",
            "",
            "- Оставляем победителей: удержание выше медианы на 30%+ или переходы в Telegram выше медианы на 50%+.",
            "- Переснимаем победителя в 3 вариантах: новый hook, другой сценарий, короче на 20-30%.",
            "- Если есть просмотры без переходов, меняем CTA.",
            "- Если есть переходы без первых сообщений, меняем onboarding бота.",
            "- Если есть вопросы в комментариях, делаем ролики-ответы на следующий день.",
        ]
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8-sig")
    print(f"Social growth board written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
