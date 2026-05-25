from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANVAS = (1080, 1920)
FPS = 24


@dataclass(frozen=True)
class AudioPreset:
    name: str
    expression: str


AUDIO_PRESETS = {
    "neon-step": AudioPreset(
        "neon-step",
        "0.10*sin(2*PI*98*t)+0.07*sin(2*PI*196*t)*(lt(mod(t,0.5),0.24))+0.045*sin(2*PI*392*t)*(lt(mod(t,0.25),0.07))+0.025*sin(2*PI*784*t)*(between(mod(t,1.0),0.72,0.84))",
    ),
    "soft-drive": AudioPreset(
        "soft-drive",
        "0.09*sin(2*PI*123*t)+0.075*sin(2*PI*246*t)*(lt(mod(t,0.375),0.16))+0.04*sin(2*PI*369*t)*(lt(mod(t,0.75),0.08))+0.025*sin(2*PI*615*t)*(gt(mod(t,0.75),0.58))",
    ),
    "clean-beat": AudioPreset(
        "clean-beat",
        "0.12*sin(2*PI*130*t)+0.055*sin(2*PI*260*t)*(lt(mod(t,0.4),0.18))+0.04*sin(2*PI*520*t)*(lt(mod(t,0.2),0.05))",
    ),
}


DEFAULT_MESSAGES = [
    "Ты опять открыл чат ночью.",
    "Мысль не отпускает?",
    "Напиши одну фразу.",
    "Нить подхватит разговор.",
    "@asknitai_bot",
]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def probe_duration(video_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def load_messages(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return DEFAULT_MESSAGES
    messages = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return messages or DEFAULT_MESSAGES


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


def cover_frame(frame: Image.Image) -> Image.Image:
    source = frame.convert("RGB")
    ratio = max(CANVAS[0] / source.width, CANVAS[1] / source.height)
    resized = source.resize((int(source.width * ratio), int(source.height * ratio)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - CANVAS[0]) // 2)
    top = max(0, (resized.height - CANVAS[1]) // 2)
    return resized.crop((left, top, left + CANVAS[0], top + CANVAS[1]))


def draw_overlay(frame: Image.Image, message: str, frame_index: int, total_frames: int) -> Image.Image:
    image = cover_frame(frame).convert("RGBA")
    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    brand_font = load_font(30)
    text_font = load_font(48)
    small_font = load_font(25)

    draw.rounded_rectangle((810, 56, 1026, 126), radius=24, fill=(5, 22, 26, 138))
    draw.text((836, 73), "Нить", font=brand_font, fill=(72, 233, 196, 245))
    draw.text((836, 103), "онлайн", font=small_font, fill=(216, 232, 230, 190))

    lines = wrap_text(draw, message, text_font, 760)[:3]
    bubble_h = 80 + 60 * len(lines)
    is_last = frame_index > total_frames * 0.78
    x = 116 if frame_index % 2 else 176
    y = 1260 if not is_last else 1390
    draw.rounded_rectangle((x, y, x + 828, y + bubble_h), radius=34, fill=(7, 29, 34, 218))
    text_y = y + 34
    for line in lines:
        draw.text((x + 38, text_y), line, font=text_font, fill=(245, 249, 247, 250))
        text_y += 60

    if is_last:
        draw.rounded_rectangle((114, 1662, 966, 1754), radius=34, fill=(5, 22, 26, 188))
        draw.text((154, 1687), "Попробовать: @asknitai_bot", font=brand_font, fill=(78, 237, 200, 250))

    draw.rectangle((0, 1800, 1080, 1920), fill=(3, 14, 17, 255))
    draw.text((736, 1844), "@asknitai_bot", font=small_font, fill=(216, 245, 239, 250))

    composed = Image.alpha_composite(image, overlay).convert("RGB")
    return ImageEnhance.Contrast(composed).enhance(1.04)


def extract_frames(source: Path, frame_dir: Path) -> int:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"fps={FPS}",
            str(frame_dir / "source_%05d.png"),
        ]
    )
    return len(list(frame_dir.glob("source_*.png")))


def create_audio(path: Path, duration: float, preset: AudioPreset) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    run(
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
            f"afade=t=in:st=0:d=0.25,afade=t=out:st={max(0.0, duration - 0.75):.2f}:d=0.55",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(path),
        ]
    )


def render_video(source: Path, output: Path, messages: list[str], preset_name: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    preset = AUDIO_PRESETS[preset_name]

    with tempfile.TemporaryDirectory(prefix="nit_kling_reel_") as temp:
        temp_dir = Path(temp)
        source_frames = temp_dir / "source"
        render_frames = temp_dir / "render"
        source_frames.mkdir()
        render_frames.mkdir()
        total_frames = extract_frames(source, source_frames)
        if total_frames <= 0:
            raise RuntimeError(f"No frames extracted from {source}")

        for index, frame_path in enumerate(sorted(source_frames.glob("source_*.png"))):
            with Image.open(frame_path) as frame:
                message_index = min(len(messages) - 1, int(index / max(total_frames, 1) * len(messages)))
                rendered = draw_overlay(frame, messages[message_index], index, total_frames)
                rendered.save(render_frames / f"frame_{index:05d}.jpg", quality=92)

        duration = probe_duration(source)
        audio_path = temp_dir / f"{preset.name}.m4a"
        create_audio(audio_path, duration, preset)
        run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(render_frames / "frame_%05d.jpg"),
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
                str(output),
            ]
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a Kling source video as a Nit social reel.")
    parser.add_argument("--source", default=str(PROJECT_ROOT / "assets/social-videos/source-videos/kling-2026-05-25-night-message.mp4"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "assets/social-videos/custom/nit-kling-night-message-neon-step.mp4"))
    parser.add_argument("--messages-file", default=str(PROJECT_ROOT / "config/kling_reel_messages.txt"))
    parser.add_argument("--preset", choices=sorted(AUDIO_PRESETS), default="neon-step")
    args = parser.parse_args()

    render_video(Path(args.source), Path(args.output), load_messages(Path(args.messages_file)), args.preset)
    print(f"Rendered {Path(args.output).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
