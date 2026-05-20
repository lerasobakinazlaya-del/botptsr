from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOT_USERNAME = "asknitai_bot"
CHANNEL = "@trynit_ai"
TZ = "Europe/Moscow"


SERIES: list[dict[str, Any]] = [
    {
        "key": "night",
        "theme": "ночной диалог",
        "title": "Когда снова не спишь",
        "pain": "В голове шумно, друзьям писать неловко, а мысль не отпускает.",
        "promise": "Нить выдерживает первый поток и помогает найти одну понятную мысль.",
        "hook": "Ты опять не спишь?",
        "cta": "Напиши Нити: «я не могу уснуть»",
        "cards": [1, 7],
    },
    {
        "key": "memory",
        "theme": "память",
        "title": "AI, который не начинает с нуля",
        "pain": "Бесит каждый раз заново объяснять контекст.",
        "promise": "Нить возвращает разговор туда, где он оборвался.",
        "hook": "Я помню, на чем мы остановились.",
        "cta": "Проверь память диалога",
        "cards": [8, 14],
    },
    {
        "key": "long-task",
        "theme": "длинная задача",
        "title": "Длинный текст не должен получать короткую отписку",
        "pain": "Ты отправляешь большой кусок, а в ответ получаешь первые две строки.",
        "promise": "Нить сначала берет суть, потом ведет разбор по частям.",
        "hook": "Скинь как есть. Я не потеряю главное.",
        "cta": "Дай Нити одну сложную задачу",
        "cards": [15, 21],
    },
    {
        "key": "not-send",
        "theme": "сообщение, которое лучше не отправлять",
        "title": "Лучшее сообщение иногда не надо отправлять человеку",
        "pain": "Хочется написать резко, но потом будет хуже.",
        "promise": "Нить помогает сначала выговориться, а потом собрать нормальную формулировку.",
        "hook": "Напиши это мне, не ему.",
        "cta": "Попроси Нить переписать сообщение",
        "cards": [22, 28],
    },
    {
        "key": "one-day",
        "theme": "дневной доступ",
        "title": "Один день, чтобы разобрать завал",
        "pain": "Иногда нужен не чат ради чата, а плотный разбор прямо сегодня.",
        "promise": "Дневной доступ включает глубину там, где появляется реальная работа.",
        "hook": "Сегодня можно распутать хотя бы один узел.",
        "cta": "Открой дневной доступ",
        "cards": [29, 35],
    },
    {
        "key": "raw-thought",
        "theme": "сырая мысль",
        "title": "Не пиши идеально. Пиши как есть",
        "pain": "Мысль еще кривая, поэтому ты откладываешь разговор.",
        "promise": "Нить задает пару вопросов и превращает хаос в следующий шаг.",
        "hook": "Начни с фразы, которую стыдно отправлять.",
        "cta": "Отправь одну недодуманную мысль",
        "cards": [36, 42],
    },
    {
        "key": "week-thread",
        "theme": "недельная нить",
        "title": "За неделю появляется рабочая нить",
        "pain": "Идеи, решения и задачи живут в разных местах.",
        "promise": "Нить держит цепочку: мысли, решения, задачи и следующий шаг.",
        "hook": "Через неделю это уже не чат, а маршрут.",
        "cta": "Начни 7-дневный диалог",
        "cards": [43, 49],
    },
]


POST_TIMES = ("12:30", "20:40")
STORY_TIMES = ("10:20", "15:40", "21:10")
SOCIAL_TIMES = ("09:10", "10:40", "12:10", "13:40", "15:10", "16:40", "18:10", "19:40", "21:10")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def parse_start(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def iso_at(day: date, hhmm: str) -> str:
    hour, minute = [int(part) for part in hhmm.split(":", 1)]
    return datetime.combine(day, time(hour, minute)).isoformat() + "+03:00"


def start_url(source: str, medium: str, content: str, campaign: str = "viral_week_01") -> str:
    return f"https://t.me/{BOT_USERNAME}?start=src_{source}__cmp_{campaign}__med_{medium}__cnt_{content}"


def post_body(day_number: int, item: dict[str, Any], variant: int) -> str:
    if variant == 1:
        return f"""
{item['hook']}

{item['pain']}

Нить нужна не для красивого ответа. Она нужна в момент, когда мысль уже крутится по кругу, а нормального собеседника рядом нет.

Попробуй коротко: напиши одну фразу, которую сейчас не хочется держать в голове.
"""
    return f"""
День {day_number} из 7: {item['theme']}.

{item['promise']}

Хороший AI-собеседник не давит советами и не делает вид, что все просто. Он помогает удержать нить разговора и выбрать следующий шаг.

Попробовать Нить можно по кнопке ниже.
"""


def build_channel_schedule(start: date) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for offset, item in enumerate(SERIES):
        day = start + timedelta(days=offset)
        for variant, publish_time in enumerate(POST_TIMES, start=1):
            post_id = f"{day.isoformat()}-{item['key']}-p{variant}"
            text_file = f"docs/channel-posts/{post_id}.md"
            write_text(PROJECT_ROOT / text_file, post_body(offset + 1, item, variant))
            card_index = item["cards"][0] if variant == 1 else item["cards"][1]
            image_file = f"assets/message-cards/week-01/card-{card_index:02d}.png"
            items.append(
                {
                    "id": post_id,
                    "enabled": True,
                    "publish_at": iso_at(day, publish_time),
                    "text_file": text_file,
                    "image_file": image_file,
                    "preview_image_file": image_file,
                    "button_text": "Попробовать Нить",
                    "button_url": start_url("telegram", "channel", f"{item['key']}_p{variant}"),
                    "pin": offset == 0 and variant == 1,
                }
            )
    return {"timezone": TZ, "default_chat_id": CHANNEL, "items": items}


def story_frames(item: dict[str, Any], variant: int) -> list[dict[str, str]]:
    variants = [
        [
            item["hook"],
            item["pain"],
            "Сначала просто напиши как есть. Без красивой формулировки.",
            item["promise"],
            "Если цепляет, открой Нить и продолжи диалог.",
        ],
        [
            "Сообщение, которое не хочется отправлять человеку, можно сначала отправить Нити.",
            "Так ты не взорвешь разговор и не останешься один на один с шумом в голове.",
            item["hook"],
            "Нить задаст один спокойный вопрос и поможет выбрать тон.",
            item["cta"],
        ],
        [
            "Мини-проверка: какая мысль возвращается к тебе чаще всего?",
            item["pain"],
            "Запиши ее одной фразой.",
            "Нить разложит ее на факты, чувства и следующий шаг.",
            "Попробуй один диалог сегодня.",
        ],
    ]
    return [{"bubble_text": text} for text in variants[(variant - 1) % len(variants)]]


def build_story_schedule(start: date) -> dict[str, Any]:
    backgrounds = [
        "assets/story-backgrounds/story-bg-01.png",
        "assets/story-backgrounds/story-bg-02.png",
        "assets/story-backgrounds/story-bg-03.png",
        "assets/story-backgrounds/story-bg-04.png",
    ]
    items: list[dict[str, Any]] = []
    for offset, item in enumerate(SERIES):
        day = start + timedelta(days=offset)
        for variant, publish_time in enumerate(STORY_TIMES, start=1):
            story_id = f"{day.isoformat()}-{item['key']}-s{variant}"
            frames = story_frames(item, variant)
            bubble_text = frames[0]["bubble_text"]
            items.append(
                {
                    "id": story_id,
                    "enabled": True,
                    "publish_at": iso_at(day, publish_time),
                    "background_file": backgrounds[(offset + variant - 1) % len(backgrounds)],
                    "image_file": f"assets/stories/daily/{story_id}.png",
                    "video_file": f"assets/stories/daily/{story_id}.mp4",
                    "headline": "Нить онлайн",
                    "bubble_text": bubble_text,
                    "frames": frames,
                    "caption": f"{item['cta']}: {start_url('tg', 'story', item['key'])}",
                }
            )
    return {
        "timezone": TZ,
        "delivery_chat_env": "STORY_DELIVERY_CHAT_ID",
        "delivery_fallback": "OWNER_ID",
        "reel_file": "assets/stories/daily/nit-week-1-reel.mp4",
        "items": items,
    }


def build_social_schedule() -> dict[str, Any]:
    hooks = [
        ("pov", "POV", "Смотри, как один текст превращается в нормальный следующий шаг."),
        ("dialog", "Экранный диалог", "Не идеальный промпт, а живой кусок мысли. Так и должно быть."),
        ("challenge", "Мини-челлендж", "Попробуй написать Нити одну фразу и не объяснять всю жизнь заново."),
        ("comment", "Ответ на комментарий", "Да, бот должен помнить контекст, иначе это не диалог."),
        ("night", "Ночная сцена", "Если снова листаешь телефон ночью, начни с одной честной фразы."),
        ("before-send", "Перед отправкой", "Сначала напиши это Нити, потом решишь, отправлять ли человеку."),
        ("free-vs-paid", "Free vs Premium", "Бесплатно можно попробовать, глубину включаем там, где появилась работа."),
        ("one-question", "Один вопрос", "Иногда достаточно одного точного вопроса, чтобы стало тише."),
        ("serial", "Серия дня", "Это не одиночный ролик, а серия: каждый день одна новая нить."),
    ]
    items: list[dict[str, Any]] = []
    for day_index, item in enumerate(SERIES, start=1):
        for variant_index, (suffix, format_name, caption_extra) in enumerate(hooks, start=1):
            start_card, end_card = item["cards"]
            span = end_card - start_card + 1
            card_start = start_card + ((variant_index - 1) % span)
            card_end = min(end_card, card_start + 2)
            if card_end - card_start < 2:
                card_start = max(start_card, end_card - 2)
                card_end = end_card
            items.append(
                {
                    "id": f"day{day_index:02d}_{item['key'].replace('-', '_')}_{suffix}",
                    "day": day_index,
                    "status": "ready",
                    "pillar": item["key"],
                    "format": format_name,
                    "publish_time": SOCIAL_TIMES[variant_index - 1],
                    "title": item["title"],
                    "hook": item["hook"],
                    "card_range": [card_start, card_end],
                    "duration_sec": 9,
                    "caption": f"{caption_extra} {item['cta']}.",
                    "cta": item["cta"],
                }
            )
    return {
        "campaign": "viral_week_01",
        "product": {
            "brand_name": "Нить",
            "public_handle": f"@{BOT_USERNAME}",
            "link_label": f"Попробовать: @{BOT_USERNAME}",
            "primary_url_template": "https://t.me/{username}?start={start_parameter}",
            "source_cards_dir": "assets/message-cards/week-01",
        },
        "bot_username": BOT_USERNAME,
        "timezone": TZ,
        "output_root": "assets/social-videos/week-01",
        "share_render_across_platforms": True,
        "music": {
            "enabled": True,
            "file": "content-factory/music/ambient-night-01.m4a",
            "volume": 0.16,
        },
        "safe_zones": {"top": 210, "bottom": 360},
        "platforms": {
            "tiktok": {
                "label": "TikTok",
                "source": "tt",
                "medium": "short",
                "daily_target": 9,
                "caption_suffix": "Ссылка на бота в профиле.",
            },
            "reels": {
                "label": "Instagram Reels",
                "source": "ig",
                "medium": "reels",
                "daily_target": 9,
                "caption_suffix": "Попробуй Нить в Telegram.",
            },
            "shorts": {
                "label": "YouTube Shorts",
                "source": "yt",
                "medium": "shorts",
                "daily_target": 9,
                "caption_suffix": "Открой Нить по ссылке в описании.",
            },
        },
        "items": items,
    }


def write_operating_model(start: date) -> None:
    write_text(
        PROJECT_ROOT / "docs" / "growth-content-operating-model.md",
        f"""
# Контент-завод Нити

Период: `{start.isoformat()}` - `{(start + timedelta(days=6)).isoformat()}`.

## Ежедневная норма

- Telegram-канал: 2 поста в день, оба с картинкой и кнопкой в бота.
- Telegram Stories: 3 готовых видео в день, бот присылает владельцу для ручной публикации.
- TikTok / Reels / Shorts: 9 разных роликов в день, каждый можно загрузить на 3 платформы.
- Физически MP4 один, но публикации и аналитика считаются отдельно: TikTok, Reels, Shorts.

## Как пытаемся вируситься

- Первые 1-2 секунды: не описание продукта, а узнаваемая ситуация.
- Один ролик = одна боль: ночь, память, длинная задача, сообщение, дневной доступ, сырая мысль.
- CTA не общий: не «переходи», а «напиши Нити конкретную фразу».
- Победителей масштабируем вариациями, а не меняем стиль каждый день.

## Что смотреть каждый день

- Досмотр и удержание первых 3 секунд.
- Сохранения и пересылки.
- Переходы в Telegram.
- Старт бота после перехода.
- Первое сообщение в боте.
- Клики Premium / оплаты Stars или ЮKassa.

## Рабочие команды

```powershell
python scripts/generate_growth_content_plan.py --start-date {start.isoformat()}
python scripts/generate_story_assets.py
python scripts/generate_message_card_pack.py
python scripts/generate_social_videos.py
python scripts/analyze_social_metrics.py
```
""",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the 7-day viral growth content plan.")
    parser.add_argument("--start-date", default=(date.today() + timedelta(days=1)).isoformat())
    args = parser.parse_args()

    start = parse_start(args.start_date)
    write_json(PROJECT_ROOT / "config" / "channel_schedule.json", build_channel_schedule(start))
    write_json(PROJECT_ROOT / "config" / "story_schedule.json", build_story_schedule(start))
    write_json(PROJECT_ROOT / "config" / "social_video_schedule.json", build_social_schedule())
    write_operating_model(start)
    print(f"Generated 7-day growth content plan from {start.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
