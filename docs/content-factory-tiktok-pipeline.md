# TikTok как часть контент-завода

Правильная схема такая:

```text
генерация сцен
-> JSON ролика
-> render_short.py
-> renders/master mp4
-> exports/tiktok + exports/shorts + exports/reels
-> ручная/API публикация
-> Telegram
-> analytics
```

TikTok здесь не главный продукт и не отдельная соцсеть. Это один из экспортов и тест эмоций: какая фраза удержала, какую переслали, после какой пошли в Telegram.

## Структура

```text
content-factory/
  scenes/
  messages/
  renders/
  exports/
    tiktok/
    shorts/
    reels/
  captions/
  music/
  analytics/
```

## Быстрый рендер

```powershell
python render_short.py night_001
```

На выходе:

```text
content-factory/renders/night_001.mp4
content-factory/exports/tiktok/night_001.mp4
content-factory/exports/tiktok/night_001.txt
content-factory/exports/tiktok/night_001-cover.jpg
content-factory/exports/shorts/night_001.mp4
content-factory/exports/reels/night_001.mp4
```

## JSON ролика

```json
{
  "id": "night_001",
  "platform": ["tiktok", "shorts", "reels"],
  "duration": 8,
  "scene": "night_room",
  "hook": "ты опять не спишь?",
  "ending": "@trynit_ai"
}
```

Полная схема лежит в `content-factory/schemas/short_schema.json`.

## Ритм

Минимум: 2 ролика в день.

Рабочий режим: 5 роликов в день, из них:

- 2 тихих ночных ролика;
- 1 продуктовый ролик;
- 1 ролик с вопросом/хуком;
- 1 повтор победившей эмоции с другой фразой.

## Аналитика

Файлы под аналитику:

- `content-factory/analytics/top_hooks.json`
- `content-factory/analytics/retention.csv`
- `content-factory/analytics/saves.csv`
- `content-factory/analytics/publish_queue.json`
- `content-factory/analytics/publish_queue.csv`

Смотрим не лайки отдельно, а цепочку:

```text
удержание -> досмотры -> сохранения -> переходы в Telegram -> старт бота -> первое сообщение -> оплата
```

## Отдельный сервис

Контент-завод не должен зависеть от runtime основного Telegram-бота. Бот отвечает за продукт, оплату, память и диалог. Завод отвечает за производство контента:

```text
content-factory/messages/*.json
-> render_short.py
-> scripts/content_factory_pipeline.py
-> content-factory/exports/<platform>/
-> scripts/content_factory_publish.py
-> analytics/publish_queue.*
```

GitHub Actions workflow `Content factory pipeline` запускает это отдельно от `Deploy Bot`.

## Автовыгрузка

Сейчас рабочая модель такая:

- `telegram`: можно публиковать автоматически через Bot API, если заданы `BOT_TOKEN` и `CONTENT_FACTORY_TELEGRAM_CHAT_ID`.
- `tiktok`: готовим exports автоматически; live upload включается после TikTok app, OAuth и approval `video.publish`.
- `shorts`: готовим exports автоматически; upload включается после Google OAuth и YouTube Data API.
- `reels`: готовим exports автоматически; upload включается после Meta app, Instagram Professional account, токена и публичного URL для видео.

Команды:

```powershell
python scripts\content_factory_pipeline.py --all
python scripts\content_factory_publish.py
python scripts\content_factory_publish.py --platform telegram --live
```
