from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish a UTF-8 Telegram channel post.")
    parser.add_argument("--chat-id", default="@trynit_ai", help="Channel username or chat id.")
    parser.add_argument("--text-file", required=True, help="UTF-8 text file to publish.")
    parser.add_argument("--image-file", default="", help="Optional image to publish before the text.")
    parser.add_argument("--button-text", default="", help="Optional inline button text.")
    parser.add_argument("--button-url", default="", help="Optional inline button URL.")
    parser.add_argument("--disable-web-preview", action="store_true", help="Disable Telegram link preview.")
    parser.add_argument("--pin", action="store_true", help="Pin the published message.")
    parser.add_argument("--delete-message-id", type=int, default=0, help="Delete a previous message first.")
    parser.add_argument("--token-env", default="BOT_TOKEN", help="Environment variable with bot token.")
    return parser.parse_args()


def telegram_call(token: str, method: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Telegram {method} failed: {error_body}") from exc


def telegram_multipart_call(token: str, method: str, payload: dict, files: dict[str, Path]) -> dict:
    boundary = "----nit-telegram-boundary"
    chunks: list[bytes] = []
    for key, value in payload.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for key, path in files.items():
        data = path.read_bytes()
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{key}"; filename="{path.name}"\r\n'
                "Content-Type: image/png\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Telegram {method} failed: {error_body}") from exc


def main() -> None:
    args = parse_args()
    load_dotenv(".env")
    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"{args.token_env} is not set.")

    text = Path(args.text_file).read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("Text file is empty.")

    if args.delete_message_id:
        telegram_call(
            token,
            "deleteMessage",
            {"chat_id": args.chat_id, "message_id": args.delete_message_id},
        )
        print(f"Deleted message_id={args.delete_message_id}")

    if args.image_file:
        image_path = Path(args.image_file)
        if not image_path.exists():
            raise SystemExit(f"Image file not found: {image_path}")
        photo_result = telegram_multipart_call(
            token,
            "sendPhoto",
            {"chat_id": args.chat_id},
            {"photo": image_path},
        )
        print(f"Posted photo_message_id={int(photo_result['result']['message_id'])}")

    payload = {
        "chat_id": args.chat_id,
        "text": text,
        "disable_web_page_preview": bool(args.disable_web_preview),
    }
    if args.button_text and args.button_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": args.button_text, "url": args.button_url}]],
        }

    result = telegram_call(token, "sendMessage", payload)
    message_id = int(result["result"]["message_id"])
    print(f"Posted message_id={message_id}")

    if args.pin:
        telegram_call(
            token,
            "pinChatMessage",
            {"chat_id": args.chat_id, "message_id": message_id, "disable_notification": True},
        )
        print(f"Pinned message_id={message_id}")


if __name__ == "__main__":
    main()
