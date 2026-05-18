# Telegram Channel Launch

Telegram channel creation is a manual owner action. The bot can prepare the launch kit, links, copy, and metrics, but it cannot create a channel for the owner account.

## Setup

1. Create a public Telegram channel.
2. Use title from `launch.content_studio.telegram_channel.title`.
3. Use description from `launch.content_studio.telegram_channel.description`.
4. Export `assets/launch-card.svg` to PNG and use it as the first visual direction.
5. Put the bot deep link into the pinned post.
6. Add the bot as admin only if it needs to publish later.

## Generate Kit

```powershell
python scripts\generate_telegram_channel_kit.py
```

The generated file is written to `logs/telegram_channel_kit.md`.

## First 5 Posts

- Pinned: what the product is and how to start.
- Memory demo: why saved context matters.
- Long-task demo: why day pass exists.
- Build in public: what changed this week.
- Soft CTA: ask users to send one real task to the bot.

## Tracking

Use a unique Telegram source parameter:

```text
src_telegram__cmp_pilot_day_1__med_channel__cnt_channel_seed_01
```

After publishing, watch:

- `onboarding_started` by source/campaign
- `onboarding_completed`
- `offer_shown`
- `invoice_opened`
- `paid`
- second/third message rate
