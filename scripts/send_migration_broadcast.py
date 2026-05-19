from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv


DEFAULT_LINK = "https://t.me/asknitai_bot?start=migration_old_bot"
DEFAULT_TEXT = (
    "Мы переносим Нить в новый бот, чтобы собрать продукт в одном стиле и дальше развивать его чище.\n\n"
    "Новый вход здесь:\n"
    f"{DEFAULT_LINK}\n\n"
    "Там обновленный профиль, стартовая карточка, режимы и дальнейшие улучшения."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a one-time migration broadcast from the old Telegram bot to known users.",
    )
    parser.add_argument("--db-path", default="bot.db", help="SQLite database path.")
    parser.add_argument(
        "--token-env",
        default="OLD_BOT_TOKEN",
        help="Environment variable containing the old bot token. Required with --send.",
    )
    parser.add_argument("--link", default=DEFAULT_LINK, help="New bot deep link.")
    parser.add_argument("--message-file", help="Optional UTF-8 text file with broadcast body.")
    parser.add_argument("--limit", type=int, default=0, help="Max recipients, 0 means all.")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N recipients.")
    parser.add_argument(
        "--exclude-user-id",
        action="append",
        type=int,
        default=[],
        help="Telegram user ID to skip. Can be passed multiple times.",
    )
    parser.add_argument(
        "--exclude-user-ids",
        default="",
        help="Comma-separated Telegram user IDs to skip.",
    )
    parser.add_argument("--pause", type=float, default=0.08, help="Pause between sends in seconds.")
    parser.add_argument("--button-text", default="Открыть новую Нить", help="Inline button text.")
    parser.add_argument("--send", action="store_true", help="Actually send messages. Default is dry-run.")
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="Finish with exit code 0 even when some recipients cannot be reached.",
    )
    return parser.parse_args()


def load_message(path: str | None, link: str) -> str:
    if not path:
        return DEFAULT_TEXT.replace(DEFAULT_LINK, link)
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("Message file is empty.")
    return text


def load_user_ids(db_path: str, *, limit: int, offset: int) -> list[int]:
    db = Path(db_path)
    if not db.exists():
        raise SystemExit(f"Database not found: {db}")

    query = "SELECT id FROM users ORDER BY id"
    params: list[int] = []
    if limit > 0:
        query += " LIMIT ? OFFSET ?"
        params.extend([max(1, limit), max(0, offset)])
    elif offset > 0:
        query += " LIMIT -1 OFFSET ?"
        params.append(offset)

    with sqlite3.connect(db) as connection:
        rows = connection.execute(query, params).fetchall()
    return [int(row[0]) for row in rows]


def parse_excluded_user_ids(args: argparse.Namespace) -> set[int]:
    user_ids = set(args.exclude_user_id)
    for raw_value in args.exclude_user_ids.replace(";", ",").split(","):
        value = raw_value.strip()
        if not value:
            continue
        try:
            user_ids.add(int(value))
        except ValueError as exc:
            raise SystemExit(f"Invalid user ID in --exclude-user-ids: {value}") from exc
    return user_ids


def make_keyboard(text: str, link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, url=link)]],
    )


async def send_one(
    bot: Bot,
    user_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> tuple[bool, str]:
    try:
        await bot.send_message(user_id, text, reply_markup=keyboard)
        return True, "sent"
    except TelegramRetryAfter as exc:
        await asyncio.sleep(float(exc.retry_after))
        try:
            await bot.send_message(user_id, text, reply_markup=keyboard)
            return True, "sent_after_retry"
        except Exception as retry_exc:  # noqa: BLE001 - result is logged, not re-raised.
            return False, type(retry_exc).__name__
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        return False, type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - keep broadcast running for other users.
        return False, type(exc).__name__


async def send_broadcast(args: argparse.Namespace) -> int:
    load_dotenv()
    user_ids = load_user_ids(args.db_path, limit=args.limit, offset=args.offset)
    excluded_user_ids = parse_excluded_user_ids(args)
    if excluded_user_ids:
        user_ids = [user_id for user_id in user_ids if user_id not in excluded_user_ids]
    text = load_message(args.message_file, args.link)

    print(f"Recipients: {len(user_ids)}")
    print(f"Excluded recipients: {len(excluded_user_ids)}")
    print(f"Mode: {'send' if args.send else 'dry-run'}")
    print(f"Link: {args.link}")
    print("Preview:")
    print(text)

    if not args.send:
        if user_ids:
            print(f"First recipient ids: {', '.join(str(value) for value in user_ids[:10])}")
        print("Dry-run only. Add --send and set OLD_BOT_TOKEN to send.")
        return 0

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"{args.token_env} is required when --send is used.")

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"migration_broadcast_{stamp}.jsonl"

    sent = 0
    failed = 0
    keyboard = make_keyboard(args.button_text, args.link)

    async with Bot(token=token) as bot:
        with log_path.open("w", encoding="utf-8") as log_file:
            for index, user_id in enumerate(user_ids, start=1):
                ok, status = await send_one(bot, user_id, text, keyboard)
                sent += 1 if ok else 0
                failed += 0 if ok else 1
                log_file.write(
                    json.dumps(
                        {
                            "user_id": user_id,
                            "ok": ok,
                            "status": status,
                            "sent_at": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                if index % 25 == 0 or index == len(user_ids):
                    print(f"Progress: {index}/{len(user_ids)} sent={sent} failed={failed}")
                if args.pause > 0 and index < len(user_ids):
                    await asyncio.sleep(args.pause)

    print(f"Done. Sent={sent}, failed={failed}, total={len(user_ids)}")
    print(f"Log: {log_path}")
    return 0 if failed == 0 or args.allow_failures else 1


def main() -> None:
    raise SystemExit(asyncio.run(send_broadcast(parse_args())))


if __name__ == "__main__":
    main()
