# Новый бот Нити готов к запуску

Дата фиксации: 2026-05-19.

## Бот

- Username: `@asknitai_bot`
- Ссылка: `https://t.me/asknitai_bot`
- Имя: `Нить · AI-собеседник`
- Аватар: установлен вручную через BotFather.
- Команды: только `start`.
- Режимы и платный доступ: через inline-кнопки и основную клавиатуру внутри бота.

## Runtime

- `BOT_TOKEN` обновлен в GitHub Actions secret.
- Деплой обновляет серверный `.env` из GitHub secret.
- `launch.bot_username` указывает на `asknitai_bot`.
- Стартовая карточка: `assets/launch-card.png`.
- Аватарный исходник: `assets/nit-avatar.png`.

## Стартовые ссылки

Telegram seed:

```text
https://t.me/asknitai_bot?start=src_telegram__cmp_pilot_day_1__med_organic__cnt_channel_post
```

TikTok organic:

```text
https://t.me/asknitai_bot?start=src_tiktok__cmp_pilot_day_1__med_short_video__cnt_hook_memory
```

Instagram Reels:

```text
https://t.me/asknitai_bot?start=src_instagram__cmp_pilot_day_1__med_reels__cnt_long_task
```

## Финальная ручная проверка

1. Открыть `https://t.me/asknitai_bot`.
2. Нажать `/start`.
3. Убедиться, что пришла стартовая карточка, приветствие и кнопки.
4. Проверить режимы через кнопку режимов.
5. Проверить paywall через кнопку платного доступа.
6. Отправить тестовую длинную задачу и убедиться, что free-preview предлагает платный доступ на продолжение.
