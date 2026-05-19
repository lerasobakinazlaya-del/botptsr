# Рассылка перехода на нового бота

Новый бот: `https://t.me/asknitai_bot`.

Важно: рассылку старым пользователям нужно отправлять токеном старого бота. Новый бот не может писать людям, которые его еще не запускали.

## Текст рассылки

```text
Мы переносим Нить в новый бот, чтобы собрать продукт в одном стиле и дальше развивать его чище.

Новый вход здесь:
https://t.me/asknitai_bot?start=migration_old_bot

Там обновленный профиль, стартовая карточка, режимы и дальнейшие улучшения.
```

## Проверить список получателей

```powershell
python scripts/send_migration_broadcast.py
```

## Отправить тестово первым 5 пользователям

```powershell
$env:OLD_BOT_TOKEN="старый токен бота"
python scripts/send_migration_broadcast.py --limit 5 --send
```

## Отправить всем

```powershell
$env:OLD_BOT_TOKEN="старый токен бота"
python scripts/send_migration_broadcast.py --send
```

Скрипт пишет лог в `logs/migration_broadcast_*.jsonl`.
