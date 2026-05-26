from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
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


def video_has_audio(video_path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not video_path.exists():
        return False
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return "audio" in result.stdout


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


def render_story_card(item: dict[str, Any], output_path: Path, bubble_text: str) -> Path:
    background_path = PROJECT_ROOT / str(item["background_file"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(background_path).convert("RGB") as source:
        image = cover_resize(source, CANVAS).convert("RGBA")

    overlay = Image.new("RGBA", CANVAS, (0, 7, 10, 78))
    image.alpha_composite(overlay)
    draw = ImageDraw.Draw(image, "RGBA")

    # Keep the top clean: Telegram overlays channel avatar/name on stories.
    draw.rectangle((0, 0, CANVAS[0], 260), fill=(0, 0, 0, 18))
    draw.rectangle((0, 1510, CANVAS[0], CANVAS[1]), fill=(0, 0, 0, 38))

    name_font = load_font(24)
    bubble_font = load_font(34)
    white = (245, 255, 255, 245)
    teal = (58, 214, 178, 255)

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


def story_frame_texts(item: dict[str, Any]) -> list[str]:
    frames = item.get("frames")
    if isinstance(frames, list):
        texts = [str(frame.get("bubble_text") if isinstance(frame, dict) else frame).strip() for frame in frames]
        texts = [text for text in texts if text]
        if texts:
            return texts
    return [str(item.get("bubble_text") or "").strip()]


def render_story(item: dict[str, Any], index: int) -> Path:
    del index
    return render_story_card(
        item,
        PROJECT_ROOT / str(item["image_file"]),
        story_frame_texts(item)[0],
    )


def render_story_frames(item: dict[str, Any], index: int) -> list[Path]:
    del index
    base_path = PROJECT_ROOT / str(item["image_file"])
    frames_dir = base_path.with_suffix("")
    frame_paths: list[Path] = []
    for frame_index, text in enumerate(story_frame_texts(item), start=1):
        frame_paths.append(render_story_card(item, frames_dir / f"frame-{frame_index:02d}.png", text))
    return frame_paths


def render_image_sequence_video(image_paths: list[Path], video_path: Path, *, hold_frames: int = 30) -> Path | None:
    image_paths = [path for path in image_paths if path.exists()]
    if not image_paths:
        print("No images found for sequence video render")
        return None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found, skipping sequence video render")
        return None

    video_path.parent.mkdir(parents=True, exist_ok=True)
    fps = 24
    transition_frames = 8

    def zoomed(source: Image.Image, progress: float) -> Image.Image:
        zoom = 1.0 + 0.035 * progress
        size = (int(CANVAS[0] * zoom), int(CANVAS[1] * zoom))
        resized = source.resize(size, Image.Resampling.LANCZOS)
        left = int((resized.width - CANVAS[0]) / 2)
        top = int((resized.height - CANVAS[1]) / 2)
        return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))

    with tempfile.TemporaryDirectory(prefix="nit_story_video_") as temp_dir:
        temp_path = Path(temp_dir)
        images = [Image.open(path).convert("RGB") for path in image_paths]
        frame_index = 0
        previous: Image.Image | None = None

        for image in images:
            if previous is not None:
                previous_end = zoomed(previous, 1.0)
                for step in range(transition_frames):
                    alpha = (step + 1) / (transition_frames + 1)
                    current_start = zoomed(image, alpha * 0.2)
                    frame = Image.blend(previous_end, current_start, alpha)
                    frame.save(temp_path / f"frame_{frame_index:04d}.jpg", quality=92)
                    frame_index += 1

            for step in range(hold_frames):
                progress = step / max(hold_frames - 1, 1)
                frame = zoomed(image, progress)
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
                str(video_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for image in images:
            image.close()
    return video_path


def add_background_music(video_path: Path, schedule: dict[str, Any]) -> None:
    if video_has_audio(video_path):
        return

    music_config = dict(schedule.get("music") or {})
    if not bool(music_config.get("enabled", True)):
        return

    music_value = str(music_config.get("file") or "content-factory/music/ambient-night-01.m4a").strip()
    if not music_value:
        return

    music_path = PROJECT_ROOT / music_value
    if not music_path.exists():
        print(f"Music file not found, skipping story audio: {music_path}")
        return

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found, skipping story audio")
        return

    volume = float(music_config.get("volume", 0.14))
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
            f"volume={volume},afade=t=in:st=0:d=0.35",
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


def render_story_video(item: dict[str, Any], frame_paths: list[Path]) -> Path | None:
    video_value = str(item.get("video_file") or "").strip()
    if not video_value:
        return None
    if not frame_paths:
        frame_paths = [PROJECT_ROOT / str(item.get("image_file") or "")]
    return render_image_sequence_video(frame_paths, PROJECT_ROOT / video_value)


def render_story_reel(schedule: dict[str, Any]) -> Path | None:
    reel_value = str(schedule.get("reel_file") or "").strip()
    if not reel_value:
        return None

    image_paths = [
        PROJECT_ROOT / str(item.get("image_file") or "")
        for item in schedule.get("items") or []
        if item.get("enabled", True) and item.get("image_file")
    ]
    image_paths = [path for path in image_paths if path.exists()]
    if len(image_paths) < 2:
        print("Not enough story images for reel render")
        return None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found, skipping story reel render")
        return None

    reel_path = PROJECT_ROOT / reel_value
    reel_path.parent.mkdir(parents=True, exist_ok=True)

    fps = 24
    hold_frames = 30
    transition_frames = 8

    def zoomed(source: Image.Image, progress: float) -> Image.Image:
        zoom = 1.0 + 0.035 * progress
        size = (int(CANVAS[0] * zoom), int(CANVAS[1] * zoom))
        resized = source.resize(size, Image.Resampling.LANCZOS)
        left = int((resized.width - CANVAS[0]) / 2)
        top = int((resized.height - CANVAS[1]) / 2)
        return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))

    with tempfile.TemporaryDirectory(prefix="nit_story_reel_") as temp_dir:
        temp_path = Path(temp_dir)
        images = [Image.open(path).convert("RGB") for path in image_paths]
        frame_index = 0
        previous: Image.Image | None = None

        for image in images:
            if previous is not None:
                previous_end = zoomed(previous, 1.0)
                for step in range(transition_frames):
                    alpha = (step + 1) / (transition_frames + 1)
                    current_start = zoomed(image, alpha * 0.2)
                    frame = Image.blend(previous_end, current_start, alpha)
                    frame.save(temp_path / f"frame_{frame_index:04d}.jpg", quality=92)
                    frame_index += 1

            for step in range(hold_frames):
                progress = step / max(hold_frames - 1, 1)
                frame = zoomed(image, progress)
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
                str(reel_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for image in images:
            image.close()
    return reel_path


def generate_preview(schedule: dict[str, Any], output: Path) -> None:
    lines = [
        "# Календарь Telegram Stories",
        "",
        f"Часовой пояс: `{schedule.get('timezone', 'Europe/Moscow')}`",
        f"Доставка админу: `{schedule.get('delivery_chat_env', 'STORY_DELIVERY_CHAT_ID')}`",
        f"Рекламный ролик недели: `{schedule.get('reel_file', '')}`",
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
                f"Видео: `{item.get('video_file', '')}`",
                f"Кадров в дневном видео: `{len(story_frame_texts(item))}`",
                "",
                "Текст сторис:",
                "",
                "```text",
                textwrap.fill(str(item.get("bubble_text") or ""), width=70),
                "```",
                "",
                "Кадры видео:",
                "",
                "```text",
                "\n\n".join(f"{number}. {text}" for number, text in enumerate(story_frame_texts(item), start=1)),
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
        frame_paths = render_story_frames(item, index)
        print(f"Rendered {len(frame_paths)} frame(s) for {item.get('id')}")
        video_path = PROJECT_ROOT / str(item.get("video_file") or "")
        video = video_path if video_path.exists() and video_has_audio(video_path) else render_story_video(item, frame_paths)
        if video:
            add_background_music(video, schedule)
            print(f"Rendered {video.relative_to(PROJECT_ROOT).as_posix()}")
    reel = render_story_reel(schedule)
    if reel:
        add_background_music(reel, schedule)
        print(f"Rendered {reel.relative_to(PROJECT_ROOT).as_posix()}")
    generate_preview(schedule, Path(args.preview_file))
    print(f"Story preview written: {args.preview_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
