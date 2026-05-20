from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANVAS = (1080, 1920)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = size[0] / size[1]
    if source_ratio > target_ratio:
        crop_height = image.height
        crop_width = int(crop_height * target_ratio)
        left = int((image.width - crop_width) / 2)
        box = (left, 0, left + crop_width, crop_height)
    else:
        crop_width = image.width
        crop_height = int(crop_width / target_ratio)
        top = int((image.height - crop_height) / 2)
        box = (0, top, crop_width, top + crop_height)
    return image.crop(box).resize(size, Image.Resampling.LANCZOS)


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
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def draw_avatar(draw: ImageDraw.ImageDraw) -> None:
    x, y, size = 54, 90, 76
    teal = (58, 214, 178, 255)
    draw.ellipse((x, y, x + size, y + size), fill=(0, 15, 18, 150), outline=teal, width=3)
    draw.ellipse((x + 18, y + 24, x + 60, y + 48), outline=(72, 255, 221, 210), width=2)
    draw.arc((x + 18, y + 17, x + 62, y + 61), start=205, end=455, fill=(82, 245, 218, 225), width=3)


def render_story(item: dict[str, Any], index: int) -> Path:
    background_path = PROJECT_ROOT / str(item["background_file"])
    output_path = PROJECT_ROOT / str(item["image_file"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(background_path).convert("RGB") as source:
        image = cover_resize(source, CANVAS).convert("RGBA")

    overlay = Image.new("RGBA", CANVAS, (0, 7, 10, 78))
    image.alpha_composite(overlay)
    draw = ImageDraw.Draw(image, "RGBA")

    draw.rectangle((0, 0, CANVAS[0], 260), fill=(0, 0, 0, 42))
    draw.rectangle((0, 1510, CANVAS[0], CANVAS[1]), fill=(0, 0, 0, 38))
    draw_avatar(draw)

    title_font = load_font(30)
    status_font = load_font(23)
    name_font = load_font(24)
    bubble_font = load_font(34)
    white = (245, 255, 255, 245)
    muted = (245, 255, 255, 178)
    teal = (58, 214, 178, 255)

    draw.text((155, 92), "Нить", font=title_font, fill=white)
    draw.text((155, 128), "онлайн", font=status_font, fill=muted)
    bubble_text = str(item.get("bubble_text") or "").strip()
    bubble_x = 170 if len(bubble_text) > 66 else 300
    bubble_w = 750 if len(bubble_text) > 66 else 610
    max_text_w = bubble_w - 68
    lines = wrap_text(draw, bubble_text, bubble_font, max_text_w)
    line_h = 45
    bubble_h = max(184, 92 + line_h * len(lines))
    bubble_y = 1256 if bubble_h > 184 else 1288

    draw.rounded_rectangle(
        (bubble_x, bubble_y, bubble_x + bubble_w, bubble_y + bubble_h),
        radius=34,
        fill=(18, 37, 40, 190),
    )
    tail = [
        (bubble_x + 28, bubble_y + bubble_h - 38),
        (bubble_x - 20, bubble_y + bubble_h - 8),
        (bubble_x + 48, bubble_y + bubble_h - 12),
    ]
    draw.polygon(tail, fill=(18, 37, 40, 190))
    draw.text((bubble_x + 34, bubble_y + 22), "Нить", font=name_font, fill=teal)
    text_y = bubble_y + 64
    for line in lines:
        draw.text((bubble_x + 34, text_y), line, font=bubble_font, fill=white)
        text_y += line_h

    image.convert("RGB").save(output_path, quality=95)
    return output_path


def render_story_video(item: dict[str, Any]) -> Path | None:
    image_path = PROJECT_ROOT / str(item.get("image_file") or "")
    video_value = str(item.get("video_file") or "").strip()
    if not video_value:
        return None
    video_path = PROJECT_ROOT / video_value
    video_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found, skipping story video render")
        return None
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            "8",
            "-i",
            str(image_path),
            "-vf",
            "fps=30,format=yuv420p",
            "-movflags",
            "+faststart",
            str(video_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return video_path


def generate_preview(schedule: dict[str, Any], output: Path) -> None:
    lines = [
        "# Календарь Telegram Stories",
        "",
        f"Часовой пояс: `{schedule.get('timezone', 'Europe/Moscow')}`",
        f"Доставка админу: `{schedule.get('delivery_chat_env', 'STORY_DELIVERY_CHAT_ID')}`",
        "",
    ]
    for item in schedule.get("items") or []:
        status = "enabled" if item.get("enabled", True) else "disabled"
        lines.extend(
            [
                f"## {item.get('publish_at')} · `{status}`",
                "",
                f"ID: `{item.get('id')}`",
                f"Картинка: `{item.get('image_file')}`",
                "",
                "Текст сторис:",
                "",
                "```text",
                textwrap.fill(str(item.get("bubble_text") or ""), width=70),
                "```",
                "",
                "Caption:",
                "",
                "```text",
                str(item.get("caption") or ""),
                "```",
                "",
            ]
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily Telegram Story images.")
    parser.add_argument("--schedule-file", default=str(PROJECT_ROOT / "config" / "story_schedule.json"))
    parser.add_argument("--preview-file", default=str(PROJECT_ROOT / "docs" / "story-calendar-preview.md"))
    args = parser.parse_args()

    schedule = read_json(Path(args.schedule_file))
    for index, item in enumerate(schedule.get("items") or []):
        if not item.get("enabled", True):
            continue
        output = render_story(item, index)
        print(f"Rendered {output.relative_to(PROJECT_ROOT).as_posix()}")
        video = render_story_video(item)
        if video:
            print(f"Rendered {video.relative_to(PROJECT_ROOT).as_posix()}")
    generate_preview(schedule, Path(args.preview_file))
    print(f"Story preview written: {args.preview_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
