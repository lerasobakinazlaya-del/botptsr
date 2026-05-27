# Grok Images для контент-завода Нити

Новая схема простая: Grok Images делает только исходные визуалы, а репозиторий доводит их до публикации.

```text
Grok Images / Grok video
-> content-factory/inbox/grok
-> production_manifest.json
-> polish_social_video.py
-> validate_media_exports.py
-> delivery_queue.json
-> Telegram delivery / ручная публикация
```

## Как работать

1. Сделай изображение или видео в Grok.
2. Сохрани исходник в `content-factory/inbox/grok`.
3. Добавь item в `content-factory/manifests/production_manifest.json`.
4. Запусти:

```powershell
python scripts/polish_social_video.py --all
python scripts/validate_media_exports.py --queue content-factory/analytics/delivery_queue.json
```

5. Запусти доставку себе в Telegram:

```powershell
python scripts/deliver_social_videos.py --queue content-factory/analytics/delivery_queue.json --all --limit 3
```

## Главный принцип

В Grok не просим русский текст, кнопки, Telegram UI, TikTok UI или логотипы. Grok делает атмосферу. Скрипты делают формат, звук, safe zones, подпись, CTA и контроль качества.
