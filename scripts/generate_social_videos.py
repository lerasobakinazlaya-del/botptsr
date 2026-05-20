from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANVAS = (1080, 1920)
FPS = 24
START_PARAMETER_MAX_LENGTH = 64


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if text_width(draw, candidate, font) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word
        if current:
            lines.append(current)
    return lines


def card_paths_from_range(card_range: list[int]) -> list[Path]:
    start, end = int(card_range[0]), int(card_range[1])
    return card_paths_from_range_in_dir(PROJECT_ROOT / "assets" / "message-cards" / "week-01", start, end)


def card_paths_from_range_in_dir(source_dir: Path, start: int, end: int) -> list[Path]:
    return [
        source_dir / f"card-{index:02d}.png"
        for index in range(start, end + 1)
    ]


def build_start_parameter(item: dict[str, Any], platform_key: str, platform: dict[str, Any], campaign: str) -> str:
    content = str(item["id"]).replace("day", "d")
    replacements = {
        "before-send": "bs",
        "free-vs-paid": "fvp",
        "one-question": "oq",
        "challenge": "ch",
        "comment": "cm",
        "dialog": "dlg",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    source = str(platform.get("source") or platform_key)
    medium = str(platform.get("medium") or "short")
    value = f"src_{source}__cmp_{campaign}__med_{medium}__cnt_{content}"
    if len(value) > START_PARAMETER_MAX_LENGTH:
        raise ValueError(f"{item['id']} / {platform_key}: start parameter is too long: {len(value)}")
    return value


def build_url(product: dict[str, Any], bot_username: str, start_parameter: str) -> str:
    template = str(product.get("primary_url_template") or "")
    username = str(product.get("username") or bot_username).strip().lstrip("@")
    if template:
        return template.format(username=username, start_parameter=start_parameter)
    base_url = str(product.get("primary_url") or "").strip()
    if base_url:
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}start={start_parameter}"
    return f"https://t.me/{username}?start={start_parameter}"


def decorate_frame(
    image: Image.Image,
    item: dict[str, Any],
    platform_label: str,
    product: dict[str, Any],
    progress: float,
) -> Image.Image:
    base = image.convert("RGB").resize(CANVAS, Image.Resampling.LANCZOS)
    zoom = 1.0 + 0.028 * progress
    resized = base.resize((int(CANVAS[0] * zoom), int(CANVAS[1] * zoom)), Image.Resampling.LANCZOS)
    left = (resized.width - CANVAS[0]) // 2
    top = (resized.height - CANVAS[1]) // 2
    frame = resized.crop((left, top, left + CANVAS[0], top + CANVAS[1])).convert("RGBA")

    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.rectangle((0, 0, CANVAS[0], 330), fill=(0, 0, 0, 118))
    draw.rectangle((0, 1470, CANVAS[0], CANVAS[1]), fill=(0, 0, 0, 92))
    draw.rectangle((0, 0, CANVAS[0], CANVAS[1]), outline=(45, 217, 184, 34), width=4)

    title_font = load_font(50, bold=True)
    hook_font = load_font(34)
    meta_font = load_font(25)
    soft = (222, 245, 241, 244)
    teal = (62, 224, 188, 255)
    muted = (166, 186, 185, 230)

    brand_name = str(product.get("brand_name") or "Project")

    draw.text((70, 56), brand_name, font=meta_font, fill=teal)
    draw.text((70, 94), "живой AI-собеседник", font=meta_font, fill=muted)

    y = 148
    for line in wrap_text(draw, str(item["title"]), title_font, 880)[:2]:
        draw.text((70, y), line, font=title_font, fill=soft)
        y += 61

    hook_y = 1508
    for line in wrap_text(draw, str(item["hook"]), hook_font, 850)[:3]:
        draw.text((70, hook_y), line, font=hook_font, fill=soft)
        hook_y += 45

    return Image.alpha_composite(frame, overlay).convert("RGB")


def render_video(
    image_paths: list[Path],
    item: dict[str, Any],
    platform_label: str,
    product: dict[str, Any],
    output_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to render social videos")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    hold_frames = max(22, int(FPS * float(item.get("duration_sec", 12)) / max(len(image_paths), 1)))
    transition_frames = 5

    def zoomed(source: Image.Image, progress: float) -> Image.Image:
        zoom = 1.0 + 0.028 * progress
        size = (int(CANVAS[0] * zoom), int(CANVAS[1] * zoom))
        resized = source.resize(size, Image.Resampling.LANCZOS)
        left = int((resized.width - CANVAS[0]) / 2)
        top = int((resized.height - CANVAS[1]) / 2)
        return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))

    with tempfile.TemporaryDirectory(prefix="nit_social_video_") as temp_dir:
        temp_path = Path(temp_dir)
        frame_index = 0
        previous: Image.Image | None = None
        decorated_images: list[Image.Image] = []
        for path in image_paths:
            with Image.open(path) as source:
                decorated_images.append(decorate_frame(source.convert("RGB"), item, platform_label, product, 0.0))

        for current in decorated_images:
            if previous is not None:
                for step in range(transition_frames):
                    alpha = (step + 1) / (transition_frames + 1)
                    frame = Image.blend(previous, current, alpha)
                    frame.save(temp_path / f"frame_{frame_index:04d}.jpg", quality=92)
                    frame_index += 1
            for step in range(hold_frames):
                progress = step / max(hold_frames - 1, 1)
                frame = zoomed(current, progress)
                if step == 0:
                    frame = ImageEnhance.Contrast(frame).enhance(1.04)
                if step == hold_frames - 1:
                    frame = frame.filter(ImageFilter.UnsharpMask(radius=1.1, percent=120, threshold=3))
                frame.save(temp_path / f"frame_{frame_index:04d}.jpg", quality=92)
                frame_index += 1
            previous = current

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(temp_path / "frame_%04d.jpg"),
                "-vf",
                "format=yuv420p",
                "-r",
                str(FPS),
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def add_background_music(video_path: Path, music_config: dict[str, Any], duration_sec: float) -> None:
    if not bool(music_config.get("enabled", False)):
        return
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found, skipping background music")
        return
    music_value = str(music_config.get("file") or "").strip()
    if not music_value:
        return
    music_path = PROJECT_ROOT / music_value
    if not music_path.exists():
        print(f"Music file not found, skipping background music: {music_path}")
        return

    volume = float(music_config.get("volume", 0.16))
    fade_out_start = max(0.0, duration_sec - 1.0)
    temp_path = video_path.with_name(f"{video_path.stem}.with-audio{video_path.suffix}")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-filter:a",
            f"volume={volume},afade=t=in:st=0:d=0.35,afade=t=out:st={fade_out_start:.2f}:d=0.8",
            "-shortest",
            "-movflags",
            "+faststart",
            str(temp_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    temp_path.replace(video_path)


def write_board(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_preview(rows: list[dict[str, str]], output_path: Path) -> None:
    lines = [
        "# TikTok / Reels / Shorts: неделя 1",
        "",
        "Готовые вертикальные ролики 9:16 собираются из карточек Нити. Текст и CTA накладываются локально, поэтому русский язык не ломается и не зависит от генератора изображений.",
        "",
        "## Как использовать",
        "",
        "1. Запустить `python scripts/generate_message_card_pack.py`.",
        "2. Запустить `python scripts/generate_social_videos.py`.",
        "3. Проверить MP4 и обложки в `assets/social-videos/week-01`.",
        "4. Выложить вручную или подключить API конкретной платформы.",
        "",
        "## Ролики",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"### День {row['day']} · {row['platform']} · {row['id']}",
                "",
                f"Видео: `{row['video_file']}`",
                f"Ссылка: `{row['url']}`",
                "",
                "```text",
                textwrap.fill(row["caption"], width=82),
                "```",
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")


def write_preview(rows: list[dict[str, str]], output_path: Path) -> None:
    lines = [
        "# TikTok / Reels / Shorts: неделя 1",
        "",
        "Готовые вертикальные ролики 9:16 собираются из карточек Нити. Текст и CTA накладываются локально, поэтому русский язык не ломается и не зависит от генератора изображений.",
        "",
        "## Как использовать",
        "",
        "1. Запустить `python scripts/generate_message_card_pack.py`.",
        "2. Запустить `python scripts/generate_social_videos.py --day 1` для одного дня или без `--day` для всей недели.",
        "3. Проверить MP4 в `assets/social-videos/week-01/shared`.",
        "4. Один MP4 можно загрузить в TikTok, Reels и Shorts; в таблице остаются отдельные строки для аналитики каждой платформы.",
        "",
        "## Ролики",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"### День {row['day']} · {row['platform']} · {row['id']}",
                "",
                f"Видео: `{row['video_file']}`",
                f"Ссылка: `{row['url']}`",
                "",
                "```text",
                textwrap.fill(row["caption"], width=82),
                "```",
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate vertical videos for TikTok, Reels and YouTube Shorts.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "social_video_schedule.json"))
    parser.add_argument("--board", default=str(PROJECT_ROOT / "docs" / "social-video-board-current.csv"))
    parser.add_argument("--preview", default=str(PROJECT_ROOT / "docs" / "social-video-preview.md"))
    parser.add_argument("--day", type=int, default=0, help="Render only one campaign day. Default renders all days.")
    parser.add_argument("--limit", type=int, default=0, help="Render at most N creative items before platform export.")
    args = parser.parse_args()

    config = read_json(project_path(args.config))
    output_root = PROJECT_ROOT / str(config["output_root"])
    product = dict(config.get("product") or {})
    bot_username = str(config.get("bot_username") or product.get("username") or "")
    campaign = str(config["campaign"])
    platforms: dict[str, Any] = config["platforms"]
    source_cards_dir = PROJECT_ROOT / str(product.get("source_cards_dir") or "assets/message-cards/week-01")
    share_render_across_platforms = bool(config.get("share_render_across_platforms", True))
    music_config = dict(config.get("music") or {})
    rows: list[dict[str, str]] = []

    selected_items = [
        item
        for item in config["items"]
        if item.get("status") != "disabled" and (not args.day or int(item.get("day", 0)) == args.day)
    ]
    if args.limit > 0:
        selected_items = selected_items[: args.limit]

    for item in selected_items:
        if item.get("status") == "disabled":
            continue
        start, end = int(item["card_range"][0]), int(item["card_range"][1])
        image_paths = card_paths_from_range_in_dir(source_cards_dir, start, end)
        missing = [str(path) for path in image_paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing source cards for {item['id']}: {missing[:3]}")

        shared_video_path = output_root / "shared" / f"{item['id']}.mp4"
        if share_render_across_platforms:
            render_video(image_paths, item, "TikTok / Reels / Shorts", product, shared_video_path)
            add_background_music(shared_video_path, music_config, float(item.get("duration_sec", 12)))

        for platform_key, platform in platforms.items():
            start_parameter = build_start_parameter(item, platform_key, platform, campaign)
            url = build_url(product, bot_username, start_parameter)
            render_id = f"{item['id']}-{platform_key}"
            video_path = output_root / platform_key / f"{render_id}.mp4"
            caption = f"{item['caption']} {platform.get('caption_suffix', '')}".strip()
            if share_render_across_platforms:
                video_path = shared_video_path
            else:
                render_video(image_paths, item, str(platform["label"]), product, video_path)
                add_background_music(video_path, music_config, float(item.get("duration_sec", 12)))
            rows.append(
                {
                    "day": str(item["day"]),
                    "publish_time": str(item["publish_time"]),
                    "platform": str(platform["label"]),
                    "id": render_id,
                    "pillar": str(item["pillar"]),
                    "status": str(item["status"]),
                    "video_file": video_path.relative_to(PROJECT_ROOT).as_posix(),
                    "start_parameter": start_parameter,
                    "url": url,
                    "caption": caption,
                    "published_url": "",
                    "views": "",
                    "likes": "",
                    "comments": "",
                    "shares": "",
                    "saves": "",
                    "hold_3s": "",
                    "completion_rate": "",
                    "profile_clicks": "",
                    "bot_starts": "",
                    "paid": "",
                    "notes": "",
                }
            )
            print(f"Rendered {video_path.relative_to(PROJECT_ROOT).as_posix()}")

    if not rows:
        raise SystemExit("No social videos rendered")
    write_board(rows, project_path(args.board))
    write_preview(rows, project_path(args.preview))
    print(f"Board written: {args.board}")
    print(f"Preview written: {args.preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
