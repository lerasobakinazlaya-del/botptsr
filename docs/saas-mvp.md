# SaaS MVP

## Product Direction

Current product is not a consumer companion first. The SaaS version is:

**A control center for launching and monetizing a Telegram AI companion without a developer.**

The buyer is not the end user who chats with the bot. The buyer is the operator:

- creator with an audience
- coach, psychologist, mentor, educator
- niche community owner
- small expert business
- founder testing a paid AI companion

The end user gets a Telegram bot. The operator gets the admin panel, prompt controls, payment funnel, user CRM, metrics, and quality lab.

## Core Promise

Launch a paid Telegram AI companion in days, not months:

- configure bot identity and modes
- test reply quality before launch
- manage users and conversations
- sell paid plans inside Telegram
- track growth, retention, payments, and AI load
- improve prompts without redeploying code

## MVP Positioning

### One-Liner

AI Companion OS for Telegram: launch, tune, monetize, and monitor a paid AI bot from one dashboard.

### Short Landing Hero

**Launch a paid Telegram AI companion without building the backend.**

Configure personality, memory, paid modes, payments, broadcasts, and quality tests from one SaaS dashboard.

### What We Sell

Not "another AI bot".

We sell the operating layer around the bot:

- prompt/runtime control
- paid access and limits
- conversation quality testing
- user management
- broadcast and reactivation
- analytics and health monitoring

## MVP Scope

### Must Have

1. **Bot Setup**
   - Bot name, avatar, welcome text, menu buttons.
   - Mode catalog: free and paid modes.
   - Runtime prompt settings editable without code.

2. **Conversation Lab**
   - Test a user message against current settings.
   - Show final response.
   - Show active mode, selected model, token profile, and guardrail notes.
   - Keep regression prompts for launch checks.

3. **Monetization**
   - Free, Pro, Premium plans.
   - Daily message limits per plan.
   - Paid mode locking and preview limits.
   - Telegram payments and virtual checkout for test mode.

4. **Users CRM**
   - Search users.
   - Filter free, paid, expiring, expired.
   - View conversation history and memory preview.
   - Manually grant or remove paid access.

5. **Broadcast and Re-Engagement**
   - Send manual message to one user.
   - Send safe broadcast with preview and confirmation.
   - Re-engagement settings for users who went silent.

6. **Metrics**
   - Users, activations, messages, paid users, revenue.
   - Recent payments.
   - AI queue and OpenAI pool health.
   - Redis/database/release status.

7. **Launch Safety**
   - Prelaunch check command.
   - Product eval tests.
   - Prompt/memory safety.
   - Crisis bypass and sensitive topic guardrails.

### Should Have

- Landing copy generator for the operator's bot.
- Preset packs: coach, support, mentor, education, community.
- Simple onboarding checklist in admin dashboard.
- Export/import bot configuration as JSON.
- Payment funnel events by trigger.

### Not MVP

- True multi-tenant database isolation.
- Public self-serve signup.
- White-label custom domains.
- Team roles and permissions.
- Marketplace of bot templates.
- Visual flow builder.
- Native web chat widget.

These can come later. For now, sell it as a managed single-tenant SaaS deployment: one customer, one bot, one dashboard.

## MVP User Journey

### Operator Journey

1. Operator gets a deployed dashboard.
2. Opens Setup and edits bot identity.
3. Chooses a preset pack.
4. Tests 20 launch prompts in Conversation Lab.
5. Enables payments and packages.
6. Sends bot link to a small audience.
7. Watches users, conversations, payments, and failures.
8. Adjusts prompts and limits from the dashboard.
9. Uses broadcast/re-engagement to bring users back.

### End User Journey

1. Opens Telegram bot.
2. Gets a clear welcome and sample prompts.
3. Starts chatting.
4. Hits value before paywall.
5. Sees paid modes or limit-based paywall.
6. Pays inside Telegram.
7. Gets deeper modes, memory, and higher limits.

## Admin Dashboard Reframe

Rename mental model from "admin panel" to **Control Center**.

Suggested navigation:

- Overview
- Setup
- Conversation Lab
- Users
- Conversations
- Monetization
- Broadcasts
- Runtime
- Safety
- Health
- Logs

Current code already covers most of this. The missing product layer is onboarding and naming.

## Pricing

This is the SaaS pricing for operators, not the end-user Premium plan.

### Pilot

For first design partners.

- managed deployment
- one Telegram bot
- payments enabled
- dashboard access
- weekly tuning session

Price: custom / setup fee.

### Starter

For small creators.

- one bot
- up to defined monthly AI spend
- core dashboard
- payments
- basic metrics

### Pro

For serious operators.

- higher AI spend
- more users/messages
- re-engagement
- advanced Conversation Lab
- export/import configs

### Studio

For agencies or multiple brands.

- multiple single-tenant deployments
- custom templates
- priority support
- custom safety policies

## First SaaS Build Sprint

Goal: make the product feel like a SaaS control center, not a developer admin page.

### Sprint 1: Product Shell

- Add SaaS positioning docs and README section.
- Rename user-facing docs from "bot admin" to "control center".
- Add a setup checklist to dashboard copy.
- Make Overview show launch readiness:
  - bot configured
  - payment mode configured
  - packages enabled
  - product eval passed
  - Redis/DB healthy

### Sprint 2: Conversation Lab MVP

- Add saved test cases.
- Add pass/fail notes:
  - too long
  - repeated question
  - safety redirect
  - generic answer
  - no concrete next step
- Add "Run launch eval" button.

### Sprint 3: Operator Onboarding

- Add Setup page:
  - bot name
  - short description
  - welcome text
  - sample prompts
  - avatar path
  - primary paid offer
- Add preset selector:
  - support companion
  - mentor bot
  - focus coach
  - community assistant

### Sprint 4: Monetization Clarity

- Rename Premium copy to Plans where appropriate.
- Show plan economics:
  - free daily limit
  - paid daily limit
  - package price
  - active paid users
  - revenue last 30 days
- Add clear test payment mode badge.

## Acceptance Criteria

The SaaS MVP is credible when a new operator can answer these in 10 minutes:

- What is my bot called?
- What does it promise?
- Which modes are free vs paid?
- What does the paywall say?
- How do I test reply quality?
- How many users do I have?
- How many paid users do I have?
- Is the system healthy?
- What should I fix before launch?

If the dashboard cannot answer those quickly, it is still a technical admin panel, not SaaS.

