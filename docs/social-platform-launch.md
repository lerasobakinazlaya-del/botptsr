# Запуск TikTok, Instagram Reels и YouTube Shorts

Цель: вести Нить как SaaS-продукт, а не как разовый Telegram-бот. Каждый ролик должен приводить к измеримому действию: переход в Telegram, старт бота, первое сообщение, длинный диалог, paywall, оплата.

## Что нужно создать вручную

Аккаунты создаются владельцем, потому что нужны телефон, почта, подтверждения, 2FA и принятие правил платформ.

| Платформа | Что создать | Рекомендуемый handle | Ссылка в профиле |
| --- | --- | --- | --- |
| TikTok | Creator/Business account | `trynit_ai` | `https://t.me/asknitai_bot?start=src_tt__cmp_profile__med_bio__cnt_main` |
| Instagram | Creator/Business account + Facebook Page | `trynit.ai` | `https://t.me/asknitai_bot?start=src_ig__cmp_profile__med_bio__cnt_main` |
| YouTube | Channel | `@trynit_ai` | `https://t.me/asknitai_bot?start=src_yt__cmp_profile__med_bio__cnt_main` |

Описание профиля:

```text
Нить — AI-собеседник в Telegram: живой диалог, память контекста и разбор длинных задач.
Попробовать бесплатно ↓
```

## Автоматизация по платформам

### YouTube Shorts

Можно автоматизировать через YouTube Data API `videos.insert`.

Нужно:

- Google Cloud project;
- YouTube Data API v3 enabled;
- OAuth consent screen;
- OAuth client;
- refresh token со scope `youtube.upload`;
- secret `GOOGLE_CLIENT_ID`;
- secret `GOOGLE_CLIENT_SECRET`;
- secret `YOUTUBE_REFRESH_TOKEN`.

Формат:

- 9:16;
- до 60 секунд;
- MP4;
- `#Shorts` в title или description.

### Instagram Reels

Можно автоматизировать через Instagram Graph API.

Нужно:

- Instagram Business или Creator;
- привязка к Facebook Page;
- Meta app;
- long-lived access token;
- права на публикацию контента;
- secret `META_LONG_LIVED_ACCESS_TOKEN`;
- secret `INSTAGRAM_ACCOUNT_ID`.

Fallback до подключения API: готовим MP4 и подпись, публикуем вручную.

### TikTok

Автопостинг возможен через TikTok Content Posting API Direct Post, но публичная публикация требует app review. До review публикации могут быть ограничены private mode.

Нужно:

- TikTok Developer app;
- Content Posting API;
- OAuth;
- user consent;
- app review для public posting;
- secrets `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`.

Fallback до review: готовим MP4 и подпись, публикуем вручную.

## Ритм первой недели

Первые 7 дней делаем `5-7 роликов в день` суммарно по TikTok, Reels и Shorts.

Распределение:

- утром: 2 быстрых hook-ролика;
- днём: 2 продуктовых demo-ролика;
- вечером: 1-2 тёплых story-ролика;
- опционально: 1 ответ на комментарий или повтор победившего формата.

Минимум:

- TikTok: 2 ролика в день;
- Reels: 1 ролик в день;
- Shorts: 1 ролик в день.

Если формат выигрывает:

- TikTok: до 4 роликов в день;
- Reels: до 2 роликов в день;
- Shorts: до 2 роликов в день.

## Форматы, которые тестируем

1. `POV-задача`: человек пишет неровную мысль, Нить помогает не потерять контекст.
2. `Экранный диалог`: запись Telegram-чата с живым продолжением.
3. `Мини-сериал 7 дней с Нитью`: каждый день один сценарий использования.
4. `До/после`: хаос в заметках против одного диалога с памятью.
5. `Комментарий → ролик`: отвечаем на вопросы “помнит?”, “чем лучше?”, “длинные задачи?”, “как оплатить?”.

## Критерии “залетело”

Смотрим через 2 часа, 24 часа и 48 часов.

Ролик считается победителем, если есть минимум 2 из 3:

- удержание выше медианы аккаунта на 30%+;
- переходы в Telegram выше медианы на 50%+;
- комментарии/сохранения показывают интерес к продукту, а не только к теме.

Базовые ориентиры:

- 3s hold: 65%+;
- average watch time: 60%+ длины ролика;
- completion rate: 35%+ для 20-30 секунд;
- CTR в Telegram: 1.5-3%+ от просмотров;
- активация: пользователь написал боту после перехода.

## Что делаем каждый вечер

1. Убиваем нижние 30-40% форматов по удержанию и переходам.
2. Победителей переснимаем в 3 вариантах: новый hook, другой сценарий, короче на 20-30%.
3. Комментарии превращаем в 2 ролика-ответа.
4. Если удержание есть, а переходов нет, меняем CTA.
5. Если переходы есть, а первых сообщений нет, меняем onboarding в боте.
6. Если оплат нет, не давим скидками, а уточняем ценность day access/Pro/Premium.

## Метрики

Файл для ежедневного заполнения: `docs/social-metrics.csv`.

Минимальные поля:

```text
date,platform,creative_id,published_url,views,likes,comments,shares,saves,profile_clicks,bot_starts,first_messages,three_plus_messages,paywall_views,premium_clicks,paid_users,revenue_rub,notes
```

Главная логика: лайки не равны росту. Рост — это `views → profile_clicks → bot_starts → first_messages → three_plus_messages → payment intent`.
