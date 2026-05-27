from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "content-factory" / "manifests" / "production_manifest.json"
DEFAULT_QUEUE = PROJECT_ROOT / "content-factory" / "analytics" / "delivery_queue.json"
CANVAS_FILTER = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is required")
    return exe


def ffprobe_has_audio(path: Path) -> bool:
    exe = shutil.which("ffprobe")
    if not exe or not path.exists():
        return False
    result = subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return "audio" in result.stdout


def platform_output_path(output_root: Path, item_id: str, platform: str) -> Path:
    return output_root / item_id / f"{platform}.mp4"


def render_from_video(source: Path, output: Path, music_path: Path, *, volume: float, music_required: bool) -> None:
    ffmpeg = ffmpeg_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_has_audio = ffprobe_has_audio(source)
    use_music = music_required or not source_has_audio

    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if use_music:
        if not music_path.exists():
            raise FileNotFoundError(f"Music file not found: {music_path}")
        command.extend(["-stream_loop", "-1", "-i", str(music_path)])
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                CANVAS_FILTER,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-filter:a",
                f"volume={volume},afade=t=in:st=0:d=0.25",
                "-shortest",
            ]
        )
    else:
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-vf",
                CANVAS_FILTER,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        )
    command.extend(["-movflags", "+faststart", str(output)])
    subprocess.run(command, check=True)


def render_from_images(sources: list[Path], output: Path, music_path: Path, *, volume: float, duration_sec: float) -> None:
    ffmpeg = ffmpeg_path()
    if not music_path.exists():
        raise FileNotFoundError(f"Music file not found: {music_path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    list_path = output.parent / "images.ffconcat"
    per_image = max(1.0, duration_sec / max(len(sources), 1))
    lines = ["ffconcat version 1.0"]
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(f"Source image not found: {source}")
        lines.append(f"file '{source.as_posix()}'")
        lines.append(f"duration {per_image:.3f}")
    lines.append(f"file '{sources[-1].as_posix()}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-safe",
            "0",
            "-f",
            "concat",
            "-i",
            str(list_path),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-vf",
            CANVAS_FILTER,
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-filter:a",
            f"volume={volume},afade=t=in:st=0:d=0.25",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
    )


def polish_item(item: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    output_root = PROJECT_ROOT / str(defaults.get("output_root") or "content-factory/exports/production")
    music_path = PROJECT_ROOT / str(defaults.get("music_file") or "content-factory/music/ambient-night-01.m4a")
    volume = float(defaults.get("music_volume", 0.16))
    source_files = [PROJECT_ROOT / str(value) for value in item.get("source_files") or []]
    if not source_files:
        raise ValueError(f"{item.get('id')}: source_files is empty")
    for source in source_files:
        if not source.exists():
            raise FileNotFoundError(f"{item.get('id')}: source file not found: {source}")

    queue_items: list[dict[str, Any]] = []
    for platform in item.get("platforms") or []:
        output = platform_output_path(output_root, str(item["id"]), str(platform))
        if item.get("source_type") == "images":
            render_from_images(
                source_files,
                output,
                music_path,
                volume=volume,
                duration_sec=float(item.get("min_duration_sec") or 9),
            )
        else:
            render_from_video(
                source_files[0],
                output,
                music_path,
                volume=volume,
                music_required=bool(item.get("music_required", True)),
            )

        meta = {
            "id": f"{item['id']}-{platform}",
            "source_id": item["id"],
            "platform": platform,
            "status": "ready_manual",
            "publish_at": item.get("publish_at", ""),
            "video_file": output.relative_to(PROJECT_ROOT).as_posix(),
            "caption": item.get("caption", ""),
            "hook": item.get("hook", ""),
            "cta": item.get("cta", ""),
            "music_required": bool(item.get("music_required", True)),
            "min_duration_sec": item.get("min_duration_sec", 6),
            "max_duration_sec": item.get("max_duration_sec", 60),
            "min_unique_frames": item.get("min_unique_frames", 2),
        }
        write_json(output.with_suffix(".json"), meta)
        queue_items.append(meta)
    return queue_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Polish Grok/manual media into production-ready exports.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--id", default="", help="Polish one manifest item.")
    parser.add_argument("--all", action="store_true", help="Polish all ready/draft manifest items.")
    args = parser.parse_args()

    manifest = read_json(Path(args.manifest))
    defaults = dict(manifest.get("defaults") or {})
    items = list(manifest.get("items") or [])
    selected = [
        item
        for item in items
        if (args.all or not args.id or item.get("id") == args.id) and item.get("status") in {"draft", "ready", "polished"}
    ]
    if args.id:
        selected = [item for item in selected if item.get("id") == args.id]
    if not selected:
        raise SystemExit("No manifest items selected.")

    queue_items: list[dict[str, Any]] = []
    for item in selected:
        queue_items.extend(polish_item(item, defaults))

    queue = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": queue_items,
    }
    write_json(Path(args.queue), queue)
    print(json.dumps(queue, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
