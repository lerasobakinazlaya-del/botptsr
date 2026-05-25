# Аккаунты и публикации

Обновлено: 2026-05-25.

## Что уже работает

- Telegram-доставка оператору: включена.
- Stories для ручной публикации: бот присылает готовые MP4.
- TikTok / Reels / Shorts для ручной публикации: бот присылает MP4 и отдельное сообщение с текстами для трех площадок.
- Трекинг-ссылки в бота: генерируются отдельно для TikTok, Reels и Shorts, но не вставляются в публичные описания вручную.

## Что еще не подключено

- TikTok API: нет `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.
- Instagram Graph API: нет `META_APP_ID`, `META_APP_SECRET`, `INSTAGRAM_ACCOUNT_ID`, `META_PAGE_ID`, `META_LONG_LIVED_ACCESS_TOKEN`.
- YouTube Data API: нет `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.

## Профили

TikTok:

- Рекомендуемый username: `trynit_ai`.
- Ссылка в профиле: `https://t.me/asknitai_bot`.
- Bio: `Нить. AI-собеседник, когда мысль застряла. Попробуй в Telegram.`

Instagram:

- Рекомендуемый username: `trynit.ai` или `trynit_ai`.
- Ссылка в профиле: `https://t.me/asknitai_bot`.
- Bio: `AI-собеседник в Telegram. Для ночных мыслей, длинных задач и сообщений, которые трудно отправить.`

YouTube:

- Рекомендуемый handle: `@trynit_ai`.
- Ссылка в описании канала: `https://t.me/asknitai_bot`.
- Описание: `Нить помогает продолжить мысль, разобрать длинный текст и начать диалог без неловкости.`

## Ручной процесс на сейчас

1. Бот присылает ролик.
2. Следующим сообщением бот присылает тексты для TikTok, Reels и Shorts.
3. Один MP4 можно загрузить на все три площадки.
4. В TikTok пишем `ссылка на бота в профиле`.
5. В Reels и Shorts добавляем ссылку в описание, где это доступно.
6. После публикации заносим ссылки/метрики в `docs/social-video-board-current.csv`.

## Минимум на день

- 3 ролика в TikTok.
- Те же 3 ролика в Reels.
- Те же 3 ролика в Shorts.
- 2-3 Telegram stories вручную из присланных MP4.
- 1 пост в Telegram-канал автоматически.
