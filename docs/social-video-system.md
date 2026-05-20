# Конвейер TikTok / Reels / Shorts

У нас это делается не через один случайный генератор, а через связку:

1. Сценарии и календарь лежат в `config/social_video_schedule.json`.
2. Базовые визуалы лежат в `assets/message-cards/week-01`.
3. `scripts/generate_social_videos.py` собирает вертикальные MP4 9:16, обложки, таблицу публикаций и превью.
4. Midjourney можно использовать для атмосферных исходников, но финальный русский текст накладывает наш скрипт.
5. Runway или Kling можно подключать точечно, если нужен более живой motion, а не слайд-видео.

## Что генерируется

После запуска:

```powershell
python scripts\generate_message_card_pack.py
python scripts\generate_social_videos.py
```

появляются:

- `assets/social-videos/week-01/tiktok/*.mp4`
- `assets/social-videos/week-01/reels/*.mp4`
- `assets/social-videos/week-01/shorts/*.mp4`
- `docs/social-video-board-current.csv`
- `docs/social-video-preview.md`

## Роль Midjourney

Midjourney подходит для визуального стиля: ночные сцены, телефон в руке, мягкий свет, ощущение личного сообщения. Но не стоит просить его писать русский текст на картинке: он будет ошибаться. Поэтому правильная схема такая:

```text
Midjourney scene -> our card/text renderer -> ffmpeg video -> manual/API upload
```

## Ритм первой недели

Публикуем по одному ролику в день на каждую площадку:

- TikTok: самый цепкий хук, короткое описание, ссылка в профиле.
- Reels: тот же ролик, но чуть мягче подпись и больше доверия.
- Shorts: заголовок с поисковой формулировкой и ссылка в описании.

Победителя выбираем не по лайкам, а по воронке:

```text
views -> profile clicks -> bot starts -> first messages -> 3+ messages -> paywall -> paid
```

## Автозалив

Полный автозалив возможен только после подключения аккаунтов и API:

- YouTube Shorts: Google Cloud, YouTube Data API, OAuth refresh token.
- Instagram Reels: Professional account, Meta App, Instagram Graph API, права на publish.
- TikTok: Developer App, OAuth, `video.upload` для draft или `video.publish` после review.

До подключения API у нас безопасный рабочий режим: генерация готовых MP4 и ручная публикация. Это лучше, чем костыльный userbot, потому что не рискует аккаунтами.
