from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.content_campaign_service import build_campaign_items  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an HTML preview for social creatives.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "content_campaigns.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "docs" / "social-creative-preview.html"))
    return parser.parse_args()


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def platform_label(platform: str) -> str:
    return {
        "tiktok": "TikTok",
        "instagram": "Reels",
        "telegram": "Telegram",
        "youtube": "Shorts",
    }.get(platform, platform.title() if platform else "Social")


def render_video_card(item: dict) -> str:
    shots = item.get("shot_list") or []
    shot_html = "".join(f"<li>{esc(shot)}</li>" for shot in shots)
    return f"""
    <article class="creative video">
      <div class="phone">
        <div class="phone-top">{esc(platform_label(str(item.get("platform") or "")))}</div>
        <div class="hook">{esc(item.get("hook"))}</div>
        <div class="thread"></div>
        <div class="chat">
          <div class="bubble user">У меня каша в голове.</div>
          <div class="bubble bot">Давай сначала найдем узел, а потом первый шаг.</div>
        </div>
        <div class="cta">Открой Нить в Telegram</div>
      </div>
      <div class="creative-copy">
        <div class="meta">{esc(item.get("status"))} · {esc(item.get("pillar"))}</div>
        <h2>{esc(item.get("title"))}</h2>
        <h3>Кадры</h3>
        <ol>{shot_html}</ol>
        <h3>Подпись</h3>
        <p>{esc(item.get("caption"))}</p>
        <h3>Ссылка</h3>
        <code>{esc(item.get("url"))}</code>
      </div>
    </article>
    """


def render_telegram_card(item: dict) -> str:
    shots = item.get("shot_list") or []
    shot_html = "".join(f"<li>{esc(shot)}</li>" for shot in shots)
    return f"""
    <article class="creative telegram">
      <div class="post-card">
        <div class="post-channel">Нить | AI-собеседник</div>
        <h2>{esc(item.get("title"))}</h2>
        <p>{esc(item.get("caption"))}</p>
        <a>{esc(item.get("url"))}</a>
      </div>
      <div class="creative-copy">
        <div class="meta">{esc(item.get("status"))} · Telegram channel</div>
        <h2>{esc(item.get("hook"))}</h2>
        <h3>Структура</h3>
        <ol>{shot_html}</ol>
      </div>
    </article>
    """


def render_html(items: list[dict]) -> str:
    cards = []
    for item in items:
        platform = str(item.get("platform") or "")
        cards.append(render_telegram_card(item) if platform == "telegram" else render_video_card(item))
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Нить · предпросмотр креативов</title>
  <style>
    :root {{
      --graphite:#151515;
      --milk:#f6f1e8;
      --red:#d94a38;
      --blue:#9fb8c8;
      --sage:#a8b7a1;
      --sand:#d8c4a3;
      --ink:#25211d;
      --muted:#6f675f;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      color:var(--ink);
      font-family: "Trebuchet MS", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 10% 10%, rgba(217,74,56,.16), transparent 32%),
        radial-gradient(circle at 90% 0%, rgba(159,184,200,.24), transparent 30%),
        linear-gradient(145deg, var(--milk), #eadcc7);
    }}
    header {{ max-width:1160px; margin:0 auto; padding:48px 22px 20px; }}
    h1 {{ margin:0 0 10px; font-size:clamp(36px, 7vw, 82px); line-height:.9; letter-spacing:-.06em; }}
    .lead {{ max-width:760px; font-size:18px; line-height:1.55; color:var(--muted); }}
    .grid {{ max-width:1160px; margin:0 auto; padding:20px 22px 64px; display:grid; gap:24px; }}
    .creative {{
      display:grid;
      grid-template-columns:minmax(280px, 380px) minmax(0, 1fr);
      gap:26px;
      align-items:center;
      padding:24px;
      border:1px solid rgba(21,21,21,.12);
      border-radius:30px;
      background:rgba(255,255,255,.38);
      box-shadow:0 24px 70px rgba(21,21,21,.12);
      backdrop-filter: blur(18px);
    }}
    .phone {{
      aspect-ratio:9/16;
      border-radius:38px;
      padding:22px;
      color:var(--milk);
      background:
        linear-gradient(160deg, rgba(217,74,56,.18), transparent 36%),
        radial-gradient(circle at 80% 20%, rgba(159,184,200,.24), transparent 24%),
        var(--graphite);
      border:10px solid #050505;
      display:flex;
      flex-direction:column;
      justify-content:space-between;
      overflow:hidden;
      position:relative;
    }}
    .phone:before {{
      content:"";
      position:absolute;
      inset:18% -10% auto;
      height:220px;
      border:3px solid var(--red);
      border-color:var(--red) transparent transparent var(--red);
      border-radius:50%;
      transform:rotate(-18deg);
      opacity:.88;
    }}
    .phone-top {{ position:relative; z-index:1; font-size:13px; letter-spacing:.16em; text-transform:uppercase; color:var(--sand); }}
    .hook {{ position:relative; z-index:1; margin-top:44px; font-size:32px; line-height:1; font-weight:800; letter-spacing:-.04em; }}
    .thread {{ position:relative; z-index:1; height:2px; background:linear-gradient(90deg, transparent, var(--red), transparent); margin:26px 0; }}
    .chat {{ position:relative; z-index:1; display:grid; gap:10px; }}
    .bubble {{ padding:12px 14px; border-radius:18px; line-height:1.35; font-size:14px; }}
    .bubble.user {{ background:rgba(255,255,255,.12); justify-self:end; max-width:78%; }}
    .bubble.bot {{ background:rgba(246,241,232,.92); color:var(--ink); max-width:86%; }}
    .cta {{ position:relative; z-index:1; color:var(--sand); font-weight:700; }}
    .post-card {{
      padding:26px;
      border-radius:28px;
      background:var(--graphite);
      color:var(--milk);
      min-height:420px;
      display:grid;
      align-content:start;
      gap:16px;
      position:relative;
      overflow:hidden;
    }}
    .post-card:after {{
      content:"";
      position:absolute;
      right:-80px;
      bottom:-80px;
      width:240px;
      height:240px;
      border:4px solid var(--red);
      border-radius:50%;
    }}
    .post-channel {{ color:var(--sand); font-size:13px; letter-spacing:.14em; text-transform:uppercase; }}
    .post-card h2 {{ font-size:34px; line-height:1; margin:0; }}
    .post-card p {{ white-space:pre-wrap; line-height:1.5; }}
    .post-card a {{ color:var(--blue); overflow-wrap:anywhere; }}
    .creative-copy h2 {{ margin:0 0 16px; font-size:32px; line-height:1.05; letter-spacing:-.04em; }}
    .creative-copy h3 {{ margin:18px 0 8px; font-size:12px; text-transform:uppercase; letter-spacing:.16em; color:var(--red); }}
    .creative-copy p, .creative-copy li {{ line-height:1.55; }}
    .creative-copy code {{ display:block; padding:12px; border-radius:14px; background:rgba(21,21,21,.08); overflow-wrap:anywhere; }}
    .meta {{ color:var(--muted); text-transform:uppercase; letter-spacing:.14em; font-size:12px; margin-bottom:8px; }}
    @media (max-width:820px) {{
      .creative {{ grid-template-columns:1fr; }}
      .phone {{ max-width:360px; margin:0 auto; width:100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Предпросмотр креативов Нити</h1>
    <p class="lead">Это не финальные MP4, а визуальная витрина контент-завода: как будут выглядеть TikTok/Reels/Shorts, какие хуки, кадры, подписи и ссылки уйдут в производство.</p>
  </header>
  <main class="grid">
    {"".join(cards)}
  </main>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    items = build_campaign_items(config)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(items), encoding="utf-8")
    print(f"Social creative preview written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
