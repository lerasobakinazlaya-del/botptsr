# Social growth board

Бренд: `Нить`
Кампания: `sw1`

## Daily targets

| Platform | Minimum | Scale when winning |
| --- | ---: | ---: |
| tiktok | 2 | 4 |
| instagram | 1 | 2 |
| youtube | 1 | 2 |

## Account setup

| Platform | Status | Automation | Profile link |
| --- | --- | --- | --- |
| tiktok | manual_setup_required | api_after_app_review_or_manual_fallback | https://t.me/asknitai_bot?start=src_tt__cmp_profile__med_bio__cnt_main |
| instagram | manual_setup_required | graph_api_after_business_or_creator_setup | https://t.me/asknitai_bot?start=src_ig__cmp_profile__med_bio__cnt_main |
| youtube | manual_setup_required | youtube_data_api | https://t.me/asknitai_bot?start=src_yt__cmp_profile__med_bio__cnt_main |

## Production queue

| Day | ID | Platform | Status | Hook | CTA |
| ---: | --- | --- | --- | --- | --- |
| 1 | `vgw1_long_text_paywall` | instagram | `ready_for_edit` | Большой текст не должен умирать на первой строке ответа. | Проверить на своём тексте |
| 1 | `vgw1_memory_name` | tiktok | `ready_for_edit` | Спроси AI: как меня зовут? Если он не помнит, диалог уже сломан. | Проверь в Telegram |
| 2 | `vgw1_night_thought` | telegram | `ready_for_edit` | Ты тогда так и не рассказал, чем всё закончилось. | Продолжить диалог |
| 2 | `vgw1_second_message` | tiktok | `ready_for_script` | Главный тест AI-бота: хочется ли ответить ему вторым сообщением? | Напиши одну фразу |
| 3 | `vgw1_build_public` | instagram | `draft` | Мы не делаем магию. Мы каждый день убираем тупые ответы бота. | Следить за разработкой |
| 3 | `vgw1_payment_meaning` | tiktok | `draft` | Платить за AI стоит только когда он реально продолжает мысль. | Сначала попробуй бесплатно |

## Evening decision rule

- Оставляем победителей: удержание выше медианы на 30%+ или переходы в Telegram выше медианы на 50%+.
- Переснимаем победителя в 3 вариантах: новый hook, другой сценарий, короче на 20-30%.
- Если есть просмотры без переходов, меняем CTA.
- Если есть переходы без первых сообщений, меняем onboarding бота.
- Если есть вопросы в комментариях, делаем ролики-ответы на следующий день.