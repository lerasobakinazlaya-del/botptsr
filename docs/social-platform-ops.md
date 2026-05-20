# Platform ops: автопостинг и статистика

Единая схема для TikTok, Instagram Reels и YouTube Shorts:

```text
asset -> platform preset -> approval gate -> publish job -> status polling -> metrics sync
```

Базовый формат ассета:

- вертикальное видео `9:16`;
- `mp4` или `mov`;
- H.264/H.265;
- AAC audio;
- title;
- caption;
- hashtags;
- cover;
- flags: `ai_generated`, `brand_content`;
- internal creative id.

## YouTube Shorts

Автопостинг: реален через YouTube Data API `videos.insert`.

Нужно:

- Google Cloud project;
- YouTube Data API v3;
- OAuth Client;
- refresh token канала;
- scope `https://www.googleapis.com/auth/youtube.upload`;
- для статистики `youtube.readonly` или YouTube Analytics scopes.

Ограничения:

- Shorts определяется YouTube по формату и длительности, отдельного `shorts=true` нет;
- новые или непроверенные API-проекты могут получать private-only ограничения;
- есть дневные quota/upload limits.

Метрики:

- быстрые счётчики: `viewCount`, `likeCount`, `commentCount`;
- аналитика: watch time, subscribers gained/lost, average view duration;
- часть retention-данных может потребовать ручной проверки в Studio.

Fallback:

- загрузить вручную в YouTube Studio;
- либо API-загрузка private и ручной перевод в public после проверки.

## Instagram Reels

Автопостинг: реален через Instagram Graph API для Professional account.

Нужно:

- Instagram Business или Creator;
- привязка к Facebook Page;
- Meta App;
- long-lived access token;
- `ig_user_id`;
- Page ID;
- права `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`.

Ограничения:

- для внешнего использования нужны App Review и Advanced Access;
- media container живёт 24 часа;
- нативные Reels-фичи вроде музыки/стикеров могут быть недоступны через API;
- для трендовых звуков часто нужен ручной постинг.

Метрики:

- reach/plays/views-like метрики;
- likes;
- comments;
- saved;
- shares;
- total interactions;
- profile activity.

Fallback:

- Meta Business Suite;
- ручной постинг из Instagram app.

## TikTok

Автопостинг: два режима.

- `video.upload`: отправляет draft/inbox, пользователь завершает публикацию вручную.
- `video.publish`: Direct Post, но для публичной публикации нужен TikTok audit; без audit возможен private/self-only режим.

Нужно:

- TikTok Developer app;
- Login Kit OAuth;
- user access token/open_id;
- scopes `video.upload`, `video.publish`;
- для статистики `video.list`.

Ограничения:

- Direct Post в production закладываем как отдельный этап review;
- upload URL живёт ограниченное время;
- draft fallback имеет лимиты;
- нативные эффекты/музыка требуют ручного режима.

Метрики:

- view_count;
- like_count;
- comment_count;
- share_count;
- create_time;
- duration;
- share_url;
- cover_image_url.

Fallback:

- draft upload;
- ручная публикация оператором;
- ручной ввод retention/watch time, если API не отдаёт нужный разрез.

## Приоритет внедрения

1. YouTube Shorts API: самый прямой путь к автопостингу.
2. Instagram Reels: подключить один Business/Creator аккаунт и Meta App.
3. TikTok: сначала draft fallback, потом Direct Post audit.

## Статусы публикаций

```text
queued
uploaded
processing
published
private_only
needs_manual
failed
```

## Ритм сбора статистики

Снимать snapshot:

- +1 час;
- +6 часов;
- +24 часа;
- +72 часа;
- +7 дней;
- weekly summary.

## Что считаем победителем

Победитель — не ролик с лайками, а ролик, который двигает воронку:

```text
views -> profile_clicks -> bot_starts -> first_messages -> three_plus_messages -> payment intent
```

Если удержание высокое, но переходов нет — меняем CTA.

Если переходы есть, но нет первых сообщений — меняем onboarding бота.

Если есть первые сообщения, но нет paywall/premium-click — меняем продуктовый сценарий и объяснение платного режима.
