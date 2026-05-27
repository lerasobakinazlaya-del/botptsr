from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageChops, ImageStat
except Exception:  # pragma: no cover - handled at runtime
    Image = None
    ImageChops = None
    ImageStat = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOJIBAKE_MARKERS = ("Р", "СЃ", "СЊ", "В«", "В»", "Р", "вЂ")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    report: dict[str, Any]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe(path: Path) -> dict[str, Any]:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe is required")
    result = subprocess.run(
        [
            exe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def video_stream(probe: dict[str, Any]) -> dict[str, Any] | None:
    return next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), None)


def audio_stream(probe: dict[str, Any]) -> dict[str, Any] | None:
    return next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)


def has_mojibake(text: str) -> bool:
    if not text:
        return False
    hits = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    return hits >= 3 or hits / max(len(text), 1) > 0.015


def frame_diversity(path: Path, sample_count: int = 6) -> dict[str, Any]:
    if Image is None or ImageChops is None or ImageStat is None:
        return {"checked": False, "reason": "Pillow is not installed", "unique_frames": 0}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"checked": False, "reason": "ffmpeg is not installed", "unique_frames": 0}

    with tempfile.TemporaryDirectory(prefix="nit_validate_frames_") as temp:
        temp_dir = Path(temp)
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-vf",
                f"fps=1,scale=180:-1",
                "-frames:v",
                str(sample_count),
                str(temp_dir / "frame_%02d.jpg"),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        frames = sorted(temp_dir.glob("frame_*.jpg"))
        if len(frames) < 2:
            return {"checked": True, "unique_frames": len(frames), "mean_diffs": []}

        diffs: list[float] = []
        previous = Image.open(frames[0]).convert("RGB")
        unique_frames = 1
        for frame_path in frames[1:]:
            current = Image.open(frame_path).convert("RGB")
            diff = ImageChops.difference(previous, current)
            stat = ImageStat.Stat(diff)
            mean = sum(stat.mean) / len(stat.mean)
            diffs.append(round(mean, 3))
            if mean >= 2.5:
                unique_frames += 1
            previous.close()
            previous = current
        previous.close()
        return {"checked": True, "unique_frames": unique_frames, "mean_diffs": diffs}


def validate_item(item: dict[str, Any], *, strict: bool = True) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    video_path = PROJECT_ROOT / str(item.get("video_file") or "")

    if not video_path.exists():
        return ValidationResult(False, {"id": item.get("id"), "video_file": str(video_path), "errors": ["video_file not found"]})

    probe = ffprobe(video_path)
    v_stream = video_stream(probe)
    a_stream = audio_stream(probe)
    duration = float(probe.get("format", {}).get("duration") or 0)

    if not v_stream:
        errors.append("no video stream")
    if item.get("music_required", True) and not a_stream:
        errors.append("no audio stream")

    if v_stream:
        width = int(v_stream.get("width") or 0)
        height = int(v_stream.get("height") or 0)
        codec = str(v_stream.get("codec_name") or "")
        pix_fmt = str(v_stream.get("pix_fmt") or "")
        if codec != "h264":
            errors.append(f"video codec must be h264, got {codec}")
        if width != 1080 or height != 1920:
            errors.append(f"video must be 1080x1920, got {width}x{height}")
        if pix_fmt and pix_fmt != "yuv420p":
            warnings.append(f"pix_fmt is {pix_fmt}, expected yuv420p")

    if a_stream:
        codec = str(a_stream.get("codec_name") or "")
        if codec != "aac":
            errors.append(f"audio codec must be aac, got {codec}")

    min_duration = float(item.get("min_duration_sec") or 6)
    max_duration = float(item.get("max_duration_sec") or 60)
    if duration < min_duration:
        errors.append(f"duration {duration:.2f}s is shorter than {min_duration:.2f}s")
    if duration > max_duration:
        errors.append(f"duration {duration:.2f}s is longer than {max_duration:.2f}s")

    text_fields = " ".join(str(item.get(key) or "") for key in ("caption", "hook", "cta"))
    if has_mojibake(text_fields):
        errors.append("caption/hook/cta look mojibake-encoded")

    diversity = frame_diversity(video_path)
    min_unique_frames = int(item.get("min_unique_frames") or 2)
    if diversity.get("checked") and int(diversity.get("unique_frames") or 0) < min_unique_frames:
        errors.append(f"not enough unique frames: {diversity.get('unique_frames')} < {min_unique_frames}")
    elif not diversity.get("checked") and strict:
        warnings.append(str(diversity.get("reason") or "frame diversity was not checked"))

    report = {
        "id": item.get("id"),
        "video_file": video_path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": sha256_file(video_path),
        "duration_sec": round(duration, 3),
        "video": v_stream,
        "audio": a_stream,
        "frame_diversity": diversity,
        "errors": errors,
        "warnings": warnings,
        "validated": not errors,
    }
    return ValidationResult(not errors, report)


def load_items(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    return list(payload.get("items") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate production media before Telegram delivery.")
    parser.add_argument("--queue", default=str(PROJECT_ROOT / "content-factory" / "analytics" / "delivery_queue.json"))
    parser.add_argument("--report", default=str(PROJECT_ROOT / "content-factory" / "analytics" / "media_validation_report.json"))
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()

    queue_path = Path(args.queue)
    items = load_items(queue_path)
    if not items and not args.allow_empty:
        raise SystemExit(f"No delivery queue items found: {queue_path}")

    results = [validate_item(item) for item in items]
    report = {
        "queue": queue_path.as_posix(),
        "ok": all(result.ok for result in results),
        "items": [result.report for result in results],
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
