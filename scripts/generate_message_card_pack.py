from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


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


def story_frame_texts(item: dict[str, Any]) -> list[str]:
    frames = item.get("frames")
    if isinstance(frames, list):
        texts = [str(frame.get("bubble_text") if isinstance(frame, dict) else frame).strip() for frame in frames]
        return [text for text in texts if text]
    return [str(item.get("bubble_text") or "").strip()]


def flatten_story_cards(schedule: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for day_index, item in enumerate(schedule.get("items") or [], start=1):
        if not item.get("enabled", True):
            continue
        for frame_index, text in enumerate(story_frame_texts(item), start=1):
            cards.append(
                {
                    "day": day_index,
                    "frame": frame_index,
                    "source_id": item.get("id", ""),
                    "background_file": item.get("background_file", ""),
                    "bubble_text": text,
                }
            )
    return cards


def cover_resize_variant(image: Image.Image, size: tuple[int, int], rng: random.Random) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = size[0] / size[1]
    if source_ratio > target_ratio:
        crop_height = image.height
        crop_width = int(crop_height * target_ratio)
        span = max(1, image.width - crop_width)
        left = int(span * rng.uniform(0.18, 0.82))
        box = (left, 0, left + crop_width, crop_height)
    else:
        crop_width = image.width
        crop_height = int(crop_width / target_ratio)
        span = max(1, image.height - crop_height)
        top = int(span * rng.uniform(0.05, 0.42))
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


def add_noise(image: Image.Image, rng: random.Random, amount: int = 12) -> Image.Image:
    pixels = image.load()
    for y in range(0, image.height, 2):
        for x in range(0, image.width, 2):
            delta = rng.randint(-amount, amount)
            r, g, b = pixels[x, y]
            color = tuple(max(0, min(255, value + delta)) for value in (r, g, b))
            pixels[x, y] = color
    return image


def add_atmosphere(image: Image.Image, rng: random.Random, variant: int) -> Image.Image:
    overlay = Image.new("RGBA", CANVAS, (0, 7, 10, 74 + variant % 18))
    draw = ImageDraw.Draw(overlay, "RGBA")

    for _ in range(9):
        x = rng.randint(-160, CANVAS[0] + 160)
        y = rng.randint(120, CANVAS[1] - 260)
        radius = rng.randint(24, 110)
        alpha = rng.randint(10, 36)
        color = rng.choice([(45, 210, 184, alpha), (244, 188, 121, alpha), (120, 180, 210, alpha)])
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    for step in range(0, CANVAS[1], 18):
        alpha = int(62 * (step / CANVAS[1]) ** 1.7)
        draw.rectangle((0, step, CANVAS[0], step + 18), fill=(0, 0, 0, alpha))

    return Image.alpha_composite(image.convert("RGBA"), overlay)


def render_card(card: dict[str, Any], output_path: Path, index: int) -> Path:
    rng = random.Random(7319 + index * 97)
    background_path = PROJECT_ROOT / str(card["background_file"])
    with Image.open(background_path).convert("RGB") as source:
        if index % 5 in {1, 4}:
            source = ImageOps.mirror(source)
        image = cover_resize_variant(source, CANVAS, rng)
        image = ImageEnhance.Color(image).enhance(0.78 + (index % 7) * 0.045)
        image = ImageEnhance.Contrast(image).enhance(1.02 + (index % 5) * 0.025)
        image = ImageEnhance.Brightness(image).enhance(0.82 + (index % 6) * 0.025)
        if index % 6 == 0:
            image = image.filter(ImageFilter.GaussianBlur(radius=0.45))
        image = add_noise(image, rng, amount=7)

    canvas = add_atmosphere(image.convert("RGBA"), rng, index)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((0, 0, CANVAS[0], 180), fill=(0, 0, 0, 22))
    draw.rectangle((0, 1515, CANVAS[0], CANVAS[1]), fill=(0, 0, 0, 44))

    text = str(card["bubble_text"]).strip()
    name_font = load_font(24)
    bubble_font = load_font(34)
    white = (245, 255, 255, 245)
    teal = (58, 214, 178, 255)

    wide = len(text) > 66
    bubble_w = 770 if wide else 620
    bubble_x_options = [150, 190, 260, 300, 330]
    bubble_x = bubble_x_options[index % len(bubble_x_options)]
    bubble_x = min(bubble_x, CANVAS[0] - bubble_w - 70)
    max_text_w = bubble_w - 68
    lines = wrap_text(draw, text, bubble_font, max_text_w)
    line_h = 45
    bubble_h = max(184, 92 + line_h * len(lines))
    bubble_y = 1226 + (index % 5) * 16
    if bubble_y + bubble_h > 1514:
        bubble_y = 1514 - bubble_h

    bubble_fill = (18, 37, 40, 188 + index % 18)
    draw.rounded_rectangle((bubble_x, bubble_y, bubble_x + bubble_w, bubble_y + bubble_h), radius=34, fill=bubble_fill)
    tail = [
        (bubble_x + 34, bubble_y + bubble_h - 42),
        (bubble_x - 22, bubble_y + bubble_h - 10),
        (bubble_x + 52, bubble_y + bubble_h - 12),
    ]
    draw.polygon(tail, fill=bubble_fill)
    draw.text((bubble_x + 34, bubble_y + 22), "Нить", font=name_font, fill=teal)
    text_y = bubble_y + 64
    for line in lines:
        draw.text((bubble_x + 34, text_y), line, font=bubble_font, fill=white)
        text_y += line_h

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=95)
    return output_path


def render_video(image_paths: list[Path], output_path: Path) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found, skipping video render")
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fps = 24
    hold_frames = 28
    transition_frames = 8

    def zoomed(source: Image.Image, progress: float) -> Image.Image:
        zoom = 1.0 + 0.032 * progress
        size = (int(CANVAS[0] * zoom), int(CANVAS[1] * zoom))
        resized = source.resize(size, Image.Resampling.LANCZOS)
        left = int((resized.width - CANVAS[0]) / 2)
        top = int((resized.height - CANVAS[1]) / 2)
        return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))

    with tempfile.TemporaryDirectory(prefix="nit_message_cards_") as temp_dir:
        temp_path = Path(temp_dir)
        images = [Image.open(path).convert("RGB") for path in image_paths]
        frame_index = 0
        previous: Image.Image | None = None
        for image in images:
            if previous is not None:
                previous_end = zoomed(previous, 1.0)
                for step in range(transition_frames):
                    alpha = (step + 1) / (transition_frames + 1)
                    frame = Image.blend(previous_end, zoomed(image, alpha * 0.2), alpha)
                    frame.save(temp_path / f"frame_{frame_index:04d}.jpg", quality=92)
                    frame_index += 1
            for step in range(hold_frames):
                frame = zoomed(image, step / max(hold_frames - 1, 1))
                frame.save(temp_path / f"frame_{frame_index:04d}.jpg", quality=92)
                frame_index += 1
            previous = image

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-framerate",
                str(fps),
                "-i",
                str(temp_path / "frame_%04d.jpg"),
                "-vf",
                "format=yuv420p",
                "-r",
                str(fps),
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for image in images:
            image.close()
    return output_path


def write_preview(cards: list[dict[str, Any]], image_paths: list[Path], video_paths: list[Path], output_path: Path) -> None:
    lines = [
        "# Пакет карточек Нити",
        "",
        "49 карточек в едином стиле для постов и видео.",
        "",
        "## Видео",
        "",
    ]
    for path in video_paths:
        lines.append(f"- `{path.relative_to(PROJECT_ROOT).as_posix()}`")
    lines.extend(["", "## Карточки", ""])
    for card, path in zip(cards, image_paths):
        lines.extend(
            [
                f"### {path.relative_to(PROJECT_ROOT).as_posix()}",
                "",
                f"Источник: `{card.get('source_id')}` · день `{card.get('day')}` · кадр `{card.get('frame')}`",
                "",
                "```text",
                textwrap.fill(str(card.get("bubble_text") or ""), width=76),
                "```",
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a 49-card message pack and videos for channel promotion.")
    parser.add_argument("--schedule-file", default=str(PROJECT_ROOT / "config" / "story_schedule.json"))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "assets" / "message-cards" / "week-01"))
    parser.add_argument("--preview-file", default=str(PROJECT_ROOT / "docs" / "message-card-pack-preview.md"))
    args = parser.parse_args()

    schedule = read_json(Path(args.schedule_file))
    cards = flatten_story_cards(schedule)
    if len(cards) < 25:
        raise SystemExit(f"Expected at least 25 cards, got {len(cards)}")

    output_dir = Path(args.output_dir)
    image_paths: list[Path] = []
    for index, card in enumerate(cards[:49], start=1):
        path = output_dir / f"card-{index:02d}.png"
        render_card(card, path, index)
        image_paths.append(path)
        print(f"Rendered {path.relative_to(PROJECT_ROOT).as_posix()}")

    video_paths: list[Path] = []
    for day in range(7):
        chunk = image_paths[day * 7 : day * 7 + 7]
        if len(chunk) == 7:
            video_path = output_dir / f"video-day-{day + 1:02d}.mp4"
            video = render_video(chunk, video_path)
            if video:
                video_paths.append(video)
                print(f"Rendered {video.relative_to(PROJECT_ROOT).as_posix()}")

    full_video = render_video(image_paths, output_dir / "video-week-01.mp4")
    if full_video:
        video_paths.append(full_video)
        print(f"Rendered {full_video.relative_to(PROJECT_ROOT).as_posix()}")

    write_preview(cards[:49], image_paths, video_paths, Path(args.preview_file))
    print(f"Preview written: {args.preview_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
