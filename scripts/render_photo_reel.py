from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANVAS = (1080, 1920)
FPS = 24


@dataclass(frozen=True)
class AudioPreset:
    name: str
    expression: str


AUDIO_PRESETS = {
    "warm": AudioPreset(
        "warm",
        "0.11*sin(2*PI*110*t)+0.07*sin(2*PI*220*t)+0.035*sin(2*PI*440*t)*(gt(mod(t,0.5),0.08))",
    ),
    "pulse": AudioPreset(
        "pulse",
        "0.10*sin(2*PI*92*t)+0.06*sin(2*PI*184*t)*(lt(mod(t,0.6),0.28))+0.035*sin(2*PI*368*t)*(lt(mod(t,0.3),0.08))",
    ),
    "clean-beat": AudioPreset(
        "clean-beat",
        "0.12*sin(2*PI*130*t)+0.055*sin(2*PI*260*t)*(lt(mod(t,0.4),0.18))+0.04*sin(2*PI*520*t)*(lt(mod(t,0.2),0.05))",
    ),
}


MESSAGES = [
    "Ты опять не спишь?",
    "Напиши как есть.",
    "Я помогу собрать мысль.",
    "Не отправляй сразу. Сначала выдохни.",
    "Контекст не потеряется.",
    "Начни с одной фразы.",
    "Нить рядом в Telegram.",
]


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def cover_crop(image: Image.Image, zoom: float, pan_x: float, pan_y: float) -> Image.Image:
    source = image.convert("RGB")
    ratio = max(CANVAS[0] / source.width, CANVAS[1] / source.height) * zoom
    resized = source.resize((int(source.width * ratio), int(source.height * ratio)), Image.Resampling.LANCZOS)
    extra_x = max(0, resized.width - CANVAS[0])
    extra_y = max(0, resized.height - CANVAS[1])
    left = int(extra_x * pan_x)
    top = int(extra_y * pan_y)
    return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))


def draw_bubble(frame: Image.Image, text: str, index: int) -> Image.Image:
    image = frame.convert("RGBA")
    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    brand_font = load_font(28)
    title_font = load_font(34, bold=True)
    text_font = load_font(45)
    small_font = load_font(24)

    draw.rounded_rectangle((54, 52, 262, 122), radius=24, fill=(7, 23, 27, 146))
    draw.text((78, 70), "Нить", font=brand_font, fill=(72, 233, 196, 245))
    draw.text((78, 100), "онлайн", font=small_font, fill=(216, 232, 230, 190))

    lines = wrap_text(draw, text, text_font, 780)[:3]
    bubble_h = 96 + 56 * len(lines)
    y = 1270 if index % 2 == 0 else 1180
    x = 108 if index % 3 else 176
    draw.rounded_rectangle((x, y, x + 840, y + bubble_h), radius=34, fill=(9, 35, 38, 218))
    draw.text((x + 38, y + 26), "Нить", font=title_font, fill=(70, 226, 189, 245))
    text_y = y + 76
    for line in lines:
        draw.text((x + 38, text_y), line, font=text_font, fill=(245, 249, 247, 250))
        text_y += 56

    if index == len(MESSAGES) - 1:
        cta_y = 1680
        draw.rounded_rectangle((82, cta_y, 998, cta_y + 94), radius=34, fill=(6, 24, 27, 188))
        draw.text((122, cta_y + 24), "Попробовать: @asknitai_bot", font=title_font, fill=(78, 237, 200, 250))

    composed = Image.alpha_composite(image, overlay).convert("RGB")
    return ImageEnhance.Contrast(composed).enhance(1.03)


def render_frames(source_dir: Path, frame_dir: Path, seconds_per_scene: float) -> int:
    images = sorted(source_dir.glob("scene-*.png"))
    if not images:
        raise FileNotFoundError(f"No scene images found in {source_dir}")

    frame_count = int(seconds_per_scene * FPS)
    index = 0
    for scene_index, path in enumerate(images):
        with Image.open(path) as image:
            pan_x = 0.44 if scene_index % 2 == 0 else 0.56
            pan_y = 0.48 if scene_index < 6 else 0.60
            for step in range(frame_count):
                progress = step / max(frame_count - 1, 1)
                zoom = 1.0 + (0.055 * progress if scene_index % 2 == 0 else 0.055 * (1 - progress))
                frame = cover_crop(image, zoom, pan_x, pan_y)
                if step == frame_count - 1:
                    frame = frame.filter(ImageFilter.UnsharpMask(radius=1.1, percent=110, threshold=3))
                frame = draw_bubble(frame, MESSAGES[scene_index % len(MESSAGES)], scene_index)
                frame.save(frame_dir / f"frame_{index:05d}.jpg", quality=92)
                index += 1
    return index


def create_audio(path: Path, duration: float, preset: AudioPreset) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='{preset.expression}':s=44100:d={duration:.2f}",
            "-af",
            f"afade=t=in:st=0:d=0.35,afade=t=out:st={max(0.0, duration - 1.0):.2f}:d=0.8",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
        ],
        check=True,
    )


def render_video(source_dir: Path, output_path: Path, preset_name: str, seconds_per_scene: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    preset = AUDIO_PRESETS[preset_name]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="nit_photo_reel_") as temp:
        temp_dir = Path(temp)
        frame_dir = temp_dir / "frames"
        frame_dir.mkdir()
        total_frames = render_frames(source_dir, frame_dir, seconds_per_scene)
        duration = total_frames / FPS
        audio_path = temp_dir / f"{preset.name}.m4a"
        create_audio(audio_path, duration, preset)
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(frame_dir / "frame_%05d.jpg"),
                "-i",
                str(audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a photo-based Nit reel with message fragments and upbeat audio.")
    parser.add_argument("--source-dir", default=str(PROJECT_ROOT / "assets/social-videos/source-photos/nit-photo-set-2026-05-25"))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "assets/social-videos/custom"))
    parser.add_argument("--preset", choices=sorted(AUDIO_PRESETS), default="warm")
    parser.add_argument("--seconds-per-scene", type=float, default=2.05)
    parser.add_argument("--all-presets", action="store_true")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    output_dir = Path(args.output_dir)
    presets = sorted(AUDIO_PRESETS) if args.all_presets else [args.preset]
    for preset in presets:
        output_path = output_dir / f"nit-photo-reel-{preset}.mp4"
        render_video(source_dir, output_path, preset, args.seconds_per_scene)
        print(f"Rendered {output_path.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
