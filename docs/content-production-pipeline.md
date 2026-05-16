# Content Production Pipeline

This is the operating loop for Telegram, TikTok, Instagram Reels, and short-form launch experiments.

## Roles

- Product lead: chooses the weekly hypothesis and success metric.
- SMM lead: turns the hypothesis into hooks, scripts, captions, and publishing order.
- Moderator: checks safety, language, claims, and comments before publishing.
- Analyst: reviews source/campaign funnel and decides what to repeat.
- Operator: publishes content and updates the registry with URLs and metrics.

## Weekly Loop

1. Pick 3-5 content pillars from `config/content_campaigns.json`.
2. Generate links with `python scripts/generate_content_calendar.py`.
3. Validate the pack with `python scripts/validate_content_pipeline.py`.
4. Export captions with `python scripts/export_caption_pack.py`.
5. Publish Telegram first, then TikTok/Reels.
6. Review starts, first messages, paywall views, invoices, and paid conversion by source/campaign.
7. Keep winners, rewrite weak hooks, pause unsafe or unclear claims.

## Publishing Rules

- Every post must have a unique `start_parameter`.
- Every caption must have a CTA, but no pressure on loneliness, fear, or anxiety.
- TikTok/Reels captions should be short; Telegram posts can explain the product more deeply.
- Do not promise therapy, guaranteed outcomes, or replacement for specialists.
- Russian campaigns should stay in Russian unless the creative intentionally uses English.

## Telegram Channel Setup

Create the channel manually in Telegram, because a bot cannot create a channel on behalf of the owner. Recommended structure:

- Title: `Нить: AI-собеседник`
- Description: `AI-собеседник с памятью для разборов, длинных задач и продолжения мысли.`
- Avatar: use `assets/launch-card.svg` as the visual direction or export it to PNG.
- Pinned post: use the Telegram item from `config/content_campaigns.json`.
- First posts: product promise, one memory demo, one long-task demo, one pricing/day-pass explanation.

## Metrics

Track this every day:

- views
- profile clicks
- bot starts
- first messages
- second/third message rate
- paywall views
- invoice opens
- paid users
- source/campaign conversion
