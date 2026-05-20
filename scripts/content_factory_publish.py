from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACTORY_ROOT = PROJECT_ROOT / "content-factory"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def platform_config(platform: str) -> dict[str, Any]:
    config_path = FACTORY_ROOT / "config" / "platforms.json"
    if not config_path.exists():
        return {}
    return (read_json(config_path).get(platform) or {})


def telegram_chat_id() -> str:
    configured = os.getenv("CONTENT_FACTORY_TELEGRAM_CHAT_ID", "").strip()
    if configured:
        return configured
    fallback = str(platform_config("telegram").get("default_chat_id") or "").strip()
    if fallback:
        return fallback
    return "@trynit_ai"


def multipart_request(url: str, fields: dict[str, str], files: dict[str, Path]) -> urllib.request.Request:
    boundary = f"----NitFactory{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")
    for name, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode())
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )


def send_telegram_video(meta: dict[str, Any]) -> dict[str, Any]:
    token = os.environ["BOT_TOKEN"]
    chat_id = telegram_chat_id()
    video_path = PROJECT_ROOT / meta["video_file"]
    caption_path = PROJECT_ROOT / meta["caption_file"]
    caption = read_text(caption_path)
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    request = multipart_request(
        url,
        fields={"chat_id": chat_id, "caption": caption},
        files={"video": video_path},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def export_meta_files(platform: str | None) -> list[Path]:
    pattern = f"{platform}/*.json" if platform else "*/*.json"
    return sorted((FACTORY_ROOT / "exports").glob(pattern))


def publish_or_report(meta_path: Path, live: bool) -> dict[str, Any]:
    meta = read_json(meta_path)
    platform = str(meta["platform"])
    if platform != "telegram":
        return {
            "id": meta["id"],
            "platform": platform,
            "status": "ready_manual",
            "reason": "API connector is configured as gated: use exports now, add OAuth/app review before live upload.",
            "video_file": meta["video_file"],
            "caption_file": meta["caption_file"],
        }
    missing = [name for name in ("BOT_TOKEN",) if not os.getenv(name)]
    if missing:
        return {
            "id": meta["id"],
            "platform": platform,
            "status": "needs_credentials",
            "missing_env": missing,
            "video_file": meta["video_file"],
        }
    if not live:
        return {
            "id": meta["id"],
            "platform": platform,
            "status": "dry_run_ready_api",
            "video_file": meta["video_file"],
        }
    try:
        response = send_telegram_video(meta)
    except urllib.error.URLError as error:
        return {
            "id": meta["id"],
            "platform": platform,
            "status": "failed",
            "error": str(error),
            "video_file": meta["video_file"],
        }
    return {
        "id": meta["id"],
        "platform": platform,
        "status": "published" if response.get("ok") else "failed",
        "response": response,
        "video_file": meta["video_file"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish content-factory exports where API credentials are available.")
    parser.add_argument("--platform", choices=["telegram", "tiktok", "shorts", "reels"], help="Limit platform.")
    parser.add_argument("--live", action="store_true", help="Actually publish enabled API targets. Default is dry-run.")
    args = parser.parse_args()

    results = [publish_or_report(path, args.live) for path in export_meta_files(args.platform)]
    output_path = FACTORY_ROOT / "analytics" / "publish_results.json"
    output_path.write_text(json.dumps({"items": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"items": results}, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] not in {"failed"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
