# Production-контент-завод

## Что считаем production

- `content-factory/inbox/grok` — сырье из Grok Images / Grok video.
- `content-factory/manifests/production_manifest.json` — единый план, что полировать и куда готовить.
- `content-factory/exports/production` — только готовые валидные ролики.
- `content-factory/analytics/delivery_queue.json` — очередь для отправки оператору.
- `content-factory/archive` — завершенные исходники и отчеты.
- `docs/grok-images` — промты и визуальный стандарт.

## Что считаем legacy

Старые папки `content-factory/messages`, `scenes`, `renders`, `exports/tiktok`, `exports/reels`, `exports/shorts`, `exports/telegram` остаются только для совместимости. Новые материалы туда не кладем.

## Полуавтомат

```powershell
python scripts/polish_social_video.py --all
python scripts/validate_media_exports.py --queue content-factory/analytics/delivery_queue.json
python scripts/deliver_social_videos.py --queue content-factory/analytics/delivery_queue.json --all --limit 3
```

## Автомат

GitHub Actions `Media production` запускает polish + validation + queue. После этого `Social video delivery` отправляет оператору только валидные файлы.

## Quality Gate

Delivery запрещен, если:

- нет аудиодорожки;
- не 9:16;
- видео короче минимума или длиннее максимума;
- слишком мало уникальных кадров;
- caption или JSON содержит явную битую кодировку;
- нет validation report.
