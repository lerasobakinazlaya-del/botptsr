from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parent
FACTORY_ROOT = PROJECT_ROOT / "content-factory"
CANVAS = (1080, 1920)
FPS = 24
PLATFORM_LABELS = {
    "tiktok": "TikTok",
    "shorts": "YouTube Shorts",
    "reels": "Instagram Reels",
    "telegram": "Telegram",
}


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


def resolve_message_path(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    if path.suffix != ".json":
        path = path.with_suffix(".json")
    candidate = FACTORY_ROOT / "messages" / path.name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Message JSON not found: {value}")


def resolve_factory_path(base_file: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_file.parent / path).resolve()


def platforms_for(message: dict[str, Any]) -> list[str]:
    value = message.get("platform", "tiktok")
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    return [str(value).strip().lower()]


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
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


def cover_resize(image: Image.Image) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = CANVAS[0] / CANVAS[1]
    if source_ratio > target_ratio:
        crop_height = image.height
        crop_width = int(crop_height * target_ratio)
        left = (image.width - crop_width) // 2
        box = (left, 0, left + crop_width, crop_height)
    else:
        crop_width = image.width
        crop_height = int(crop_width / target_ratio)
        top = (image.height - crop_height) // 2
        box = (0, top, crop_width, top + crop_height)
    return image.crop(box).resize(CANVAS, Image.Resampling.LANCZOS)


def zoomed(image: Image.Image, progress: float) -> Image.Image:
    zoom = 1.0 + 0.035 * progress
    resized = image.resize((int(CANVAS[0] * zoom), int(CANVAS[1] * zoom)), Image.Resampling.LANCZOS)
    left = (resized.width - CANVAS[0]) // 2
    top = (resized.height - CANVAS[1]) // 2
    return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))


def render_base_frame(background: Image.Image, scene: dict[str, Any], message: dict[str, Any]) -> Image.Image:
    if scene.get("layout") == "chat_story":
        return render_chat_story_frame(background, scene, message)

    base = cover_resize(background.convert("RGB"))
    base = ImageEnhance.Brightness(base).enhance(0.68)
    base = ImageEnhance.Contrast(base).enhance(1.08)
    base = base.filter(ImageFilter.GaussianBlur(radius=0.18)).convert("RGBA")

    palette = scene.get("palette") or {}
    overlay_color = tuple(palette.get("overlay") or [0, 10, 14, 135])
    accent = tuple(palette.get("accent") or [64, 226, 190, 255])
    text_color = tuple(palette.get("text") or [238, 250, 248, 255])
    muted = tuple(palette.get("muted") or [156, 181, 180, 230])

    overlay = Image.new("RGBA", CANVAS, overlay_color)
    frame = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(frame, "RGBA")

    hook_font = load_font(70, bold=True)
    beat_font = load_font(44)
    ending_font = load_font(38, bold=True)
    meta_font = load_font(26)

    draw.text((74, 76), "Нить", font=meta_font, fill=accent)
    draw.text((74, 112), "тихий ролик", font=meta_font, fill=muted)

    y = 290
    for line in wrap_text(draw, str(message["hook"]), hook_font, 870)[:3]:
        draw.text((74, y), line, font=hook_font, fill=text_color)
        y += 82

    beats = [str(item) for item in message.get("beats") or [] if str(item).strip()]
    beat_y = 870
    for index, beat in enumerate(beats[:4], start=1):
        alpha = 255 if index <= 2 else 225
        bullet_color = accent if index == 1 else muted
        draw.rounded_rectangle((74, beat_y + 10, 94, beat_y + 30), radius=10, fill=bullet_color)
        for line in wrap_text(draw, beat, beat_font, 800)[:2]:
            draw.text((122, beat_y), line, font=beat_font, fill=(*text_color[:3], alpha))
            beat_y += 54
        beat_y += 28

    draw.rounded_rectangle((74, 1646, 1006, 1762), radius=40, fill=(11, 35, 38, 220))
    draw.text((116, 1683), str(message.get("cta") or "Попробовать"), font=ending_font, fill=accent)
    draw.text((74, 1816), str(message["ending"]), font=ending_font, fill=text_color)
    return frame.convert("RGB")


def render_chat_story_frame(background: Image.Image, scene: dict[str, Any], message: dict[str, Any]) -> Image.Image:
    base = cover_resize(background.convert("RGB"))
    base = ImageEnhance.Brightness(base).enhance(0.82)
    base = ImageEnhance.Contrast(base).enhance(1.06)
    frame = base.convert("RGBA")

    palette = scene.get("palette") or {}
    accent = tuple(palette.get("accent") or [64, 226, 190, 255])
    text_color = tuple(palette.get("text") or [238, 250, 248, 255])
    muted = tuple(palette.get("muted") or [156, 181, 180, 230])

    overlay = Image.new("RGBA", CANVAS, (0, 8, 12, 58))
    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.rectangle((0, 0, CANVAS[0], 230), fill=(0, 0, 0, 86))
    draw.rectangle((0, 1390, CANVAS[0], CANVAS[1]), fill=(0, 0, 0, 72))
    frame = Image.alpha_composite(frame, overlay)
    draw = ImageDraw.Draw(frame, "RGBA")

    name_font = load_font(34, bold=True)
    status_font = load_font(27)
    bubble_name_font = load_font(25)
    bubble_font = load_font(42)
    time_font = load_font(26)

    avatar_x, avatar_y, avatar_size = 58, 76, 72
    draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), outline=accent, width=3, fill=(4, 22, 24, 210))
    draw.arc((avatar_x + 18, avatar_y + 20, avatar_x + 56, avatar_y + 52), 205, 565, fill=accent, width=3)
    draw.text((150, 78), str(message.get("sender") or "Нить"), font=name_font, fill=text_color)
    draw.text((150, 120), "онлайн", font=status_font, fill=muted)

    text = str(message.get("message_bubble") or message.get("hook") or "").strip()
    bubble_w = 760
    bubble_x = 252
    bubble_y = 1270
    max_text_w = bubble_w - 76
    lines = wrap_text(draw, text, bubble_font, max_text_w)[:3]
    bubble_h = max(184, 96 + len(lines) * 56)
    bubble_fill = (17, 38, 42, 220)
    draw.rounded_rectangle((bubble_x, bubble_y, bubble_x + bubble_w, bubble_y + bubble_h), radius=36, fill=bubble_fill)
    draw.polygon(
        [
            (bubble_x + 42, bubble_y + bubble_h - 46),
            (bubble_x - 24, bubble_y + bubble_h - 12),
            (bubble_x + 56, bubble_y + bubble_h - 14),
        ],
        fill=bubble_fill,
    )
    draw.text((bubble_x + 38, bubble_y + 24), str(message.get("sender") or "Нить"), font=bubble_name_font, fill=accent)

    text_y = bubble_y + 70
    for line in lines:
        draw.text((bubble_x + 38, text_y), line, font=bubble_font, fill=text_color)
        text_y += 56

    time_text = str(message.get("timecode") or "00:41")
    time_w = text_width(draw, time_text, time_font)
    draw.text((bubble_x + bubble_w - time_w - 34, bubble_y + bubble_h - 44), time_text, font=time_font, fill=muted)
    return frame.convert("RGB")


def caption_text(message: dict[str, Any]) -> str:
    caption = str(message.get("caption") or "").strip()
    hashtags = [f"#{str(tag).lstrip('#')}" for tag in message.get("hashtags") or [] if str(tag).strip()]
    if hashtags:
        return f"{caption}\n\n{' '.join(hashtags)}".strip()
    return caption


def render_mp4(base_frame: Image.Image, output_path: Path, duration: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = max(int(duration * FPS), FPS * 4)

    with tempfile.TemporaryDirectory(prefix="content_factory_short_") as temp_dir:
        temp_path = Path(temp_dir)
        for index in range(total_frames):
            progress = index / max(total_frames - 1, 1)
            frame = zoomed(base_frame, progress)
            frame.save(temp_path / f"frame_{index:04d}.jpg", quality=92)
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


def write_platform_exports(message: dict[str, Any], master_mp4: Path, base_frame: Image.Image) -> list[Path]:
    exported: list[Path] = []
    caption = caption_text(message)
    for platform in platforms_for(message):
        export_dir = FACTORY_ROOT / "exports" / platform
        export_dir.mkdir(parents=True, exist_ok=True)
        video_path = export_dir / f"{message['id']}.mp4"
        caption_path = export_dir / f"{message['id']}.txt"
        meta_path = export_dir / f"{message['id']}.json"
        shutil.copyfile(master_mp4, video_path)
        caption_path.write_text(caption, encoding="utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "id": message["id"],
                    "platform": platform,
                    "video_file": str(video_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "caption_file": str(caption_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "duration": message["duration"],
                    "hook": message["hook"],
                    "ending": message["ending"],
                    "button_text": message.get("button_text", ""),
                    "button_url": message.get("button_url", ""),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        exported.append(video_path)
    return exported


def render_short(message_path: Path) -> list[Path]:
    message = read_json(message_path)
    scene_path = FACTORY_ROOT / "scenes" / f"{message['scene']}.json"
    scene = read_json(scene_path)
    background_path = resolve_factory_path(scene_path, str(scene["background"]))
    with Image.open(background_path) as background:
        base_frame = render_base_frame(background, scene, message)

    render_dir = FACTORY_ROOT / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    master_mp4 = render_dir / f"{message['id']}.mp4"
    render_mp4(base_frame, master_mp4, float(message["duration"]))

    caption_dir = FACTORY_ROOT / "captions"
    caption_dir.mkdir(parents=True, exist_ok=True)
    (caption_dir / f"{message['id']}.txt").write_text(caption_text(message), encoding="utf-8")
    return write_platform_exports(message, master_mp4, base_frame)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one short video from content-factory/messages/*.json")
    parser.add_argument("message", help="Message id or path, for example: night_001 or content-factory/messages/night_001.json")
    args = parser.parse_args()

    message_path = resolve_message_path(args.message)
    exports = render_short(message_path)
    for path in exports:
        print(f"Exported {path.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
