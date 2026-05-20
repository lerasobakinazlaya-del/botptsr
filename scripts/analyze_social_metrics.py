from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_int(value: Any) -> int:
    raw = str(value or "").strip().replace(" ", "")
    if not raw:
        return 0
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return 0


def parse_float(value: Any) -> float:
    raw = str(value or "").strip().replace("%", "").replace(",", ".")
    if not raw:
        return 0.0
    try:
        number = float(raw)
    except ValueError:
        return 0.0
    if "%" in str(value):
        return number / 100.0
    return number


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def score_row(row: dict[str, str]) -> float:
    views = max(parse_int(row.get("views")), 1)
    bot_starts = parse_int(row.get("bot_starts"))
    profile_clicks = parse_int(row.get("profile_clicks"))
    likes = parse_int(row.get("likes"))
    comments = parse_int(row.get("comments"))
    shares = parse_int(row.get("shares"))
    saves = parse_int(row.get("saves"))
    completion_rate = parse_float(row.get("completion_rate"))
    hold_3s = parse_float(row.get("hold_3s"))
    paid = parse_int(row.get("paid"))

    engagement_rate = (likes + comments * 2 + shares * 4 + saves * 4) / views
    click_rate = profile_clicks / views
    start_rate = bot_starts / views
    paid_rate = paid / views
    return (
        hold_3s * 22
        + completion_rate * 26
        + engagement_rate * 120
        + click_rate * 180
        + start_rate * 260
        + paid_rate * 900
    )


def enrich_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        views = parse_int(row.get("views"))
        item = dict(row)
        item["score"] = round(score_row(row), 3)
        item["views_int"] = views
        item["bot_starts_int"] = parse_int(row.get("bot_starts"))
        item["paid_int"] = parse_int(row.get("paid"))
        enriched.append(item)
    enriched.sort(key=lambda item: (float(item["score"]), int(item["views_int"])), reverse=True)
    return enriched


def summarize(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    by_platform: dict[str, dict[str, Any]] = defaultdict(lambda: {"items": 0, "views": 0, "starts": 0, "paid": 0})
    by_pillar: dict[str, dict[str, Any]] = defaultdict(lambda: {"items": 0, "views": 0, "starts": 0, "paid": 0, "score": 0.0})

    for row in enriched:
        platform = str(row.get("platform") or "unknown")
        pillar = str(row.get("pillar") or "unknown")
        for bucket in (by_platform[platform], by_pillar[pillar]):
            bucket["items"] += 1
            bucket["views"] += int(row["views_int"])
            bucket["starts"] += int(row["bot_starts_int"])
            bucket["paid"] += int(row["paid_int"])
        by_pillar[pillar]["score"] += float(row["score"])

    return {
        "top_items": enriched[:15],
        "weak_items": list(reversed(enriched[-15:])) if enriched else [],
        "platforms": dict(by_platform),
        "pillars": dict(by_pillar),
    }


def write_report(summary: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Social Metrics Report",
        "",
        "Заполняй метрики в `docs/social-video-board-current.csv` или подключай API-сборщики. Этот отчет ранжирует ролики по удержанию, вовлечению, переходам, стартам бота и оплатам.",
        "",
        "## Победители",
        "",
    ]
    for row in summary["top_items"]:
        lines.extend(
            [
                f"- `{row.get('id')}` · {row.get('platform')} · score `{row.get('score')}` · views `{row.get('views_int')}` · starts `{row.get('bot_starts_int')}` · paid `{row.get('paid_int')}`",
            ]
        )
    lines.extend(["", "## Слабые ролики", ""])
    for row in summary["weak_items"]:
        lines.append(
            f"- `{row.get('id')}` · {row.get('platform')} · score `{row.get('score')}` · views `{row.get('views_int')}`"
        )
    lines.extend(["", "## Что делать завтра", ""])
    lines.append("- Повторить топ-3 хука в новых вариациях: другой первый кадр, короче текст, другой CTA.")
    lines.append("- Убрать нижние 30% форматов, если у них нет переходов в Telegram.")
    lines.append("- Если досмотры есть, а стартов бота нет, менять CTA и ссылку в описании.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze TikTok/Reels/Shorts metrics and rank winning hooks.")
    parser.add_argument("--board", default=str(PROJECT_ROOT / "docs" / "social-video-board-current.csv"))
    parser.add_argument("--json-output", default=str(PROJECT_ROOT / "content-factory" / "analytics" / "social_metrics_report.json"))
    parser.add_argument("--report", default=str(PROJECT_ROOT / "docs" / "social-metrics-report.md"))
    args = parser.parse_args()

    rows = read_rows(Path(args.board))
    enriched = enrich_rows(rows)
    summary = summarize(enriched)
    json_path = Path(args.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(summary, Path(args.report))
    print(f"Analyzed {len(rows)} social rows")
    print(f"Report written: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
