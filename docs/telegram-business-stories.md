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

## Почему Telegram пишет “бот не поддерживает Business”

Это означает, что у самого бота ещё не включён Business Mode в `@BotFather`.

Код на сервере уже готов принимать `business_connection`, но Telegram не позволит подключить бота к Business-аккаунту, пока владелец бота не включит этот режим в настройках BotFather.

## Шаг 1. Включить Business Mode у бота

Сделать это должен владелец `@asknitai_bot`, то есть аккаунт, на котором бот создан в `@BotFather`.

1. Открыть `@BotFather`.
2. Нажать или отправить команду:

```text
/mybots
```

3. Выбрать `@asknitai_bot`.
4. Открыть `Bot Settings`.
5. Найти `Business Mode`.
6. Включить Business Mode.

Если пункта `Business Mode` не видно:

1. Обновить Telegram до последней версии.
2. Открыть `@BotFather` именно с аккаунта-владельца бота.
3. Проверить, что выбран именно `@asknitai_bot`, а не старый бот.
4. Попробовать через мобильный Telegram, потому что часть новых BotFather-настроек иногда появляется там раньше.

После этого ошибка “бот не поддерживает Telegram Business” должна исчезнуть.

Источник: официальная документация Telegram по Bots for Business указывает первым шагом `Enable Business Mode for your bot in @BotFather`.

## Шаг 2. Подключить бота к Telegram Business

1. Открыть Telegram-аккаунт, от имени которого будут публиковаться сторис.
2. Включить Telegram Business для этого аккаунта.
3. Перейти в настройки Telegram Business.
4. Открыть раздел чат-ботов / Chatbots.
5. Подключить `@asknitai_bot`.
6. В правах бота включить управление сторис, то есть `can_manage_stories`.
7. После подключения бот получит update `business_connection`.
8. Наш обработчик сохранит подключение в `data/business_connections.json`.

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

## Шаг 3. Добавить ID в GitHub

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

## Быстрая проверка после включения Business Mode

1. Включить Business Mode в `@BotFather`.
2. Подключить `@asknitai_bot` в настройках Telegram Business.
3. Подождать 10-30 секунд.
4. Проверить на сервере или в репозитории наличие `data/business_connections.json`.
5. Убедиться, что у подключения:

```json
{
  "is_enabled": true,
  "can_manage_stories": true
}
```

Если `can_manage_stories` равен `false`, нужно вернуться в настройки Telegram Business и выдать боту право на управление сторис.

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
