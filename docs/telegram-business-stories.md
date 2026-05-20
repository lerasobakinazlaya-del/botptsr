# Как включить автопостинг Telegram Stories

Автогенерация сторис уже работает без дополнительных действий: workflow `Story scheduler` каждый день собирает картинки из `config/story_schedule.json` и обновляет превью.

Автопубликация в Telegram Stories требует отдельного подключения, потому что Bot API публикует сторис только через `postStory` от имени Telegram Business-аккаунта. Обычный бот не может сам выложить сторис в обычный канал.

## Что уже выпущено

- Расписание сторис: `config/story_schedule.json`.
- Генератор картинок: `scripts/generate_story_assets.py`.
- Публикатор сторис: `scripts/publish_scheduled_stories.py`.
- GitHub workflow: `.github/workflows/story-scheduler.yml`.
- Превью: `docs/story-calendar-preview.md`.
- Готовые картинки: `assets/stories/daily/`.
- Обработчик Business connection: `handlers/business.py`.

## Что нужно сделать в Telegram

1. Открыть Telegram-аккаунт, от имени которого будут публиковаться сторис.
2. Включить Telegram Business для этого аккаунта.
3. Подключить бота `@asknitai_bot` как Business-бота.
4. В правах бота включить управление сторис, то есть `can_manage_stories`.
5. После подключения бот получит update `business_connection`.
6. Наш обработчик сохранит подключение в `data/business_connections.json`.

В файле будет примерно такая структура:

```json
{
  "connections": {
    "123456789:abcdef": {
      "id": "123456789:abcdef",
      "user_id": 123456789,
      "is_enabled": true,
      "can_manage_stories": true
    }
  }
}
```

Нужное значение для публикации — поле `id`.

## Что нужно сделать в GitHub

Добавить secret в репозитории:

```text
TELEGRAM_BUSINESS_CONNECTION_ID=<id из data/business_connections.json>
```

Путь в GitHub:

```text
Repository → Settings → Secrets and variables → Actions → New repository secret
```

`BOT_TOKEN` уже используется существующими workflow. Новый secret нужен только для сторис.

## Как проверить без публикации

Локально:

```powershell
python scripts\generate_story_assets.py
python scripts\publish_scheduled_stories.py --dry-run --now 2026-05-20T11:00:00+03:00
```

В GitHub Actions:

```text
Actions → Story scheduler → Run workflow → dry_run=true
```

Dry-run должен показать `Due stories`, но ничего не отправлять.

## Как выпустить настоящую сторис

После добавления `TELEGRAM_BUSINESS_CONNECTION_ID`:

```text
Actions → Story scheduler → Run workflow → dry_run=false → limit=1
```

Если due-story есть, workflow:

1. сгенерирует картинки;
2. вызовет Telegram `postStory`;
3. сохранит `story_id` в `data/story_published.json`;
4. закоммитит состояние, чтобы не было дублей.

## Что будет, если Business connection не подключён

В режиме `dry_run=true` всё продолжит работать: картинки и очередь можно смотреть.

В режиме `dry_run=false` workflow остановится с понятной ошибкой:

```text
TELEGRAM_BUSINESS_CONNECTION_ID is not set. Stories were generated, but Telegram postStory requires a Business connection with can_manage_stories.
```

Это сделано специально: лучше увидеть ошибку, чем думать, что сторис опубликованы, когда Telegram их не принял.

## Ежедневный режим

Workflow запускается каждый день в 10:37 MSK:

```yaml
cron: "37 7 * * *"
```

Сторис в расписании стоят на 10:30 MSK, поэтому workflow запускается после наступления due-time.

## Fallback без Business

Если Business-подключение пока не готово, всё равно используем контур:

1. `Story scheduler` генерирует картинки.
2. Смотрим `docs/story-calendar-preview.md`.
3. Берём картинку из `assets/stories/daily/`.
4. Публикуем сторис вручную от аккаунта/канала, где есть право на Stories.

Так маркетинг не блокируется Telegram-ограничением, а после подключения Business тот же контур станет полностью автоматическим.
