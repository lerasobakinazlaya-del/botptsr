# Product Matrix

Goal: turn Nit from a set of working bot features into a coherent SaaS product contract.

This document is the source of truth before changing production behavior. Runtime changes should be made only after the matrix is accepted.

## Current Reality

The code already has three user plans:

| Plan | Current messages/day | Current model | Current context profile | Current access |
| --- | ---: | --- | --- | --- |
| Free | 5 | `gpt-5.4-mini` | short | `Dialog` plus daily preview of paid modes |
| Pro | 80 | `gpt-5.4-mini` | medium | all modes |
| Premium | 200 | `gpt-5.4` | deep | all modes |

Current mode names:

| Internal key | User-facing name | Current access model |
| --- | --- | --- |
| `base` | Dialog | free |
| `comfort` | Psychologist | paid, with free preview |
| `mentor` | Breakdown | paid, with free preview |
| `dominant` | Focus | paid, with free preview |

Important current implementation notes:

- Plan model routing is in `config/runtime_settings.json` under `ai.plan_overrides`.
- Runtime model selection is resolved in `services/ai_profile_service.py`.
- Daily message limits are enforced in `handlers/chat.py`.
- Paid-mode preview is enforced in `services/mode_access_service.py`.
- Payments sell packages with `plan_key` in `payment.packages`.
- Usage ledger exists in `openai_usage_events` and is written by `services/openai_client.py`.
- There is no hard monthly free message limit yet.
- There is no hard monthly per-user token limit yet.
- `is_premium` currently means "paid", not strictly "Premium". That naming is a source of confusion.

## Product Principle

Do not sell "a smarter model" as the only upgrade.

Sell a better product experience:

- more continuation;
- more context;
- more modes;
- better handling of long tasks;
- fewer interruptions;
- deeper premium escalation when it matters.

This keeps costs controllable and makes plans understandable.

## Recommended MVP Matrix

| Capability | Free | Pro | Premium |
| --- | --- | --- | --- |
| Main promise | Try the bot and feel the tone | Daily use without friction | Deep work and long context |
| Messages/day | 5 | 80 | 200 |
| Messages/month | 40 hard cap | 1,500 soft watch | 5,000 soft watch |
| Monthly token cap | 12k hard cap | 500k alert | 2M alert |
| Base mode: Dialog | full | full | full |
| Psychologist | 2 preview messages/day | full | full, deeper |
| Breakdown | 2 preview messages/day | full | full, deeper and longer |
| Focus | 2 preview messages/day | full | full, stronger profile |
| Long tasks | short preview only | practical full answer | deep answer with more context |
| Memory/history | minimal | medium | high |
| Reengagement | off | optional low-frequency | optional smarter low-frequency |
| Primary CTA | open plans after value | upgrade to Premium on long/deep tasks | renew or annual |

## Recommended Model Matrix

| Plan | Default model | Deep escalation | Why |
| --- | --- | --- | --- |
| Free | `gpt-5.4-mini` | none | strong trial experience, controlled by hard daily/monthly/token caps |
| Pro | `gpt-5.4-mini` | rare, only long task if explicitly enabled | paid plan should feel better immediately |
| Premium | `gpt-5.4-mini` | `gpt-5.4` for long task, Breakdown, high-value deep answer | avoids burning full flagship on every casual reply |

Alternative aggressive variant:

| Plan | Default model |
| --- | --- |
| Free | `gpt-5.4-mini` |
| Pro | `gpt-5.4-mini` |
| Premium | `gpt-5.4` |

This feels cleaner in marketing, but it is more expensive. Use it only after token caps and admin cost visibility are enforced.

## Model Cost Reference

Approximate standard API prices per 1M tokens. Verify before implementation.

| Model | Input | Output | Product use |
| --- | ---: | ---: | --- |
| `gpt-4o-mini` | $0.15 | $0.60 | cheapest current acquisition path |
| `gpt-4.1-mini` | $0.40 | $1.60 | better Free candidate if quality needs lift |
| `gpt-5.4-mini` | $0.75 | $4.50 | strong Pro/Premium default |
| `gpt-5.4` | $2.50 | $15.00 | Premium deep escalation only |

Sources:

- OpenAI pricing: https://openai.com/api/pricing/
- GPT-4.1 mini model page: https://developers.openai.com/api/docs/models/gpt-4.1-mini
- GPT-5.4 model page: https://developers.openai.com/api/docs/models/gpt-5.4/
- GPT-5.4 mini announcement: https://openai.com/index/introducing-gpt-5-4-mini-and-nano/

## Target Internal Contract

The product should move toward one contract object:

```json
{
  "plans": {
    "free": {
      "daily_messages": 5,
      "monthly_messages": 40,
      "monthly_chat_tokens": 12000,
      "default_model": "gpt-4o-mini",
      "max_completion_tokens": 160,
      "memory_tokens": 650,
      "history_messages": 10
    },
    "pro": {
      "daily_messages": 80,
      "monthly_messages_soft_watch": 1500,
      "monthly_chat_tokens_alert": 500000,
      "default_model": "gpt-5.4-mini",
      "max_completion_tokens": 280,
      "memory_tokens": 1100,
      "history_messages": 16
    },
    "premium": {
      "daily_messages": 200,
      "monthly_messages_soft_watch": 5000,
      "monthly_chat_tokens_alert": 2000000,
      "default_model": "gpt-5.4-mini",
      "deep_model": "gpt-5.4",
      "max_completion_tokens": 420,
      "memory_tokens": 1600,
      "history_messages": 22
    }
  }
}
```

Mode contract:

```json
{
  "modes": {
    "base": { "min_plan": "free" },
    "comfort": { "min_plan": "pro", "free_preview_daily": 2 },
    "mentor": { "min_plan": "pro", "free_preview_daily": 2, "premium_deep_escalation": true },
    "dominant": { "min_plan": "pro", "free_preview_daily": 2 }
  }
}
```

## Implementation Order

1. Create `ProductEntitlementsService`.
   - Input: user, state, runtime settings, usage.
   - Output: plan, allowed modes, remaining daily/monthly messages, token budget, paywall reason.

2. Add monthly counters.
   - `get_user_messages_count_current_month(user_id)`.
   - `get_user_chat_tokens_current_month(user_id)`.
   - Free hard caps enforced before OpenAI call.

3. Replace `is_premium` semantics.
   - Keep DB compatibility.
   - Treat `is_premium` as legacy `is_paid`.
   - Use `subscription_plan` for real product decisions.

4. Introduce `min_plan` for modes.
   - Keep `is_premium` as backward-compatible alias during migration.
   - Admin should show `Min plan`, not only `Premium` checkbox.

5. Fix paywall copy and CTA selection.
   - "Plans" is the section.
   - `Pro` is the main paid plan.
   - `Premium` is the deep upgrade.
   - Do not promise Premium limits when CTA points to Pro.

6. Add admin visibility.
   - Show Free/Pro/Premium limits in one table.
   - Show model per plan.
   - Show monthly token cap and current spend by plan/source.

7. Add release gates.
   - Matrix validation test.
   - Admin-product parity test.
   - Paywall CTA package/plan consistency test.
   - Monthly token cap enforcement test.

## Acceptance Criteria

The product is no longer a mixed feature set when these are true:

- one table answers what Free, Pro, and Premium include;
- admin shows the same table the bot actually uses;
- paywall text matches the package being sold;
- model routing is predictable from plan and task;
- free users cannot burn unlimited monthly tokens;
- Pro and Premium feel different without relying on random copy;
- docs, README, runtime config, and tests agree.

## Decision

Recommended first production version:

- Free: `5/day`, `40/month`, `12k monthly chat tokens`, `gpt-5.4-mini`.
- Pro: main paid plan, all modes, `gpt-5.4-mini`, medium context.
- Premium: deeper context and selective `gpt-5.4` escalation, not full flagship for every message.

This gives users a real taste, gives Pro a visible quality jump, and protects unit economics before paid traffic.
