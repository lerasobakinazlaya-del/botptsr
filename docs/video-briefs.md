# Video production board

Кампания: `sw1`
Бот: `@asknitai_bot`

## Как пользоваться

1. Берём ролики со статусом `ready_for_edit` первыми.
2. Исходники складываем в `assets/videos/sources/<id>/`.
3. Финальный MP4 складываем в `assets/videos/renders/<id>.mp4`.
4. После публикации заносим ссылку и метрики в таблицу роста.

## Day 1: vgw1_long_text_paywall

Статус: `ready_for_edit`
Площадка: `instagram`
Рубрика: `long_task`
Длина: `22 sec`
Формат ассетов: `story_card_plus_chat_mock`
Start parameter: `src_ig__cmp_sw1__med_reels__cnt_long`
URL: `https://t.me/asknitai_bot?start=src_ig__cmp_sw1__med_reels__cnt_long`

Хук: Большой текст не должен умирать на первой строке ответа.
Название: Длинная задача без обрыва

Сцены:
- 0-3с: показать длинный текст и просьбу «переведи целиком»
- 3-7с: плохой ответ обрывается после первых строк
- 7-13с: Нить даёт полезное начало и честно предлагает день доступа
- 13-19с: показать Stars/YooKassa как два способа оплаты
- 19-22с: CTA «не режь задачу на куски»

Исходники:
- `assets/stories/long-task-story.png`

Подпись:

```text
Для короткого вопроса хватит free. Для большого разбора нужен день доступа: https://t.me/asknitai_bot?start=src_ig__cmp_sw1__med_reels__cnt_long
```

CTA: Проверить на своём тексте
Модерация: Не использовать защищённые тексты целиком в публичном ролике.

## Day 1: vgw1_memory_name

Статус: `ready_for_edit`
Площадка: `tiktok`
Рубрика: `memory`
Длина: `18 sec`
Формат ассетов: `screen_recording_plus_story_card`
Start parameter: `src_tt__cmp_sw1__med_sv__cnt_mem`
URL: `https://t.me/asknitai_bot?start=src_tt__cmp_sw1__med_sv__cnt_mem`

Хук: Спроси AI: как меня зовут? Если он не помнит, диалог уже сломан.
Название: Бот, который не начинает с нуля

Сцены:
- 0-2с: крупный текст «Как меня зовут?»
- 2-5с: обычный бот отвечает «я не знаю»
- 5-11с: Нить достаёт имя из профиля/памяти
- 11-16с: объяснить, что память нужна для продолжения, а не для фокуса
- 16-18с: CTA «проверь на себе в Telegram»

Исходники:
- `assets/stories/memory-story.png`

Подпись:

```text
Если бот забывает контекст, разговор каждый раз начинается заново. Проверь Нить: https://t.me/asknitai_bot?start=src_tt__cmp_sw1__med_sv__cnt_mem
```

CTA: Проверь в Telegram
Модерация: Не обещать терапию или абсолютную память.

## Day 2: vgw1_night_thought

Статус: `ready_for_edit`
Площадка: `telegram`
Рубрика: `night_thought`
Длина: `10 sec`
Формат ассетов: `existing_story_mp4`
Start parameter: `src_tg__cmp_sw1__med_story__cnt_night`
URL: `https://t.me/asknitai_bot?start=src_tg__cmp_sw1__med_story__cnt_night`

Хук: Ты тогда так и не рассказал, чем всё закончилось.
Название: Сторис-подводка к диалогу

Сцены:
- 0-10с: использовать готовый MP4 без дополнительных таймеров
- caption: «Иногда продолжить проще с одной фразы»
- CTA: ссылка на бота

Исходники:
- `assets/stories/nit-story-launch.mp4`
- `assets/stories/pinned-post-story.png`

Подпись:

```text
Иногда продолжить проще с одной фразы: https://t.me/asknitai_bot?start=src_tg__cmp_sw1__med_story__cnt_night
```

CTA: Продолжить диалог
Модерация: Не давить на одиночество.

## Day 2: vgw1_second_message

Статус: `ready_for_script`
Площадка: `tiktok`
Рубрика: `dialogue`
Длина: `16 sec`
Формат ассетов: `split_screen_bad_good_answer`
Start parameter: `src_tt__cmp_sw1__med_sv__cnt_second`
URL: `https://t.me/asknitai_bot?start=src_tt__cmp_sw1__med_sv__cnt_second`

Хук: Главный тест AI-бота: хочется ли ответить ему вторым сообщением?
Название: Не справочник, а собеседник

Сцены:
- 0-2с: текст «тест: второе сообщение»
- 2-6с: шаблонный ответ обычного бота
- 6-12с: Нить отвечает с живым продолжением
- 12-16с: CTA «напиши одну честную фразу»

Исходники:
- `assets/stories/week-summary-story.png`

Подпись:

```text
Мы меряем не лайки, а желание продолжить разговор. Попробуй: https://t.me/asknitai_bot?start=src_tt__cmp_sw1__med_sv__cnt_second
```

CTA: Напиши одну фразу
Модерация: Не изображать эмоциональную зависимость от бота.

## Day 3: vgw1_build_public

Статус: `draft`
Площадка: `instagram`
Рубрика: `build_in_public`
Длина: `18 sec`
Формат ассетов: `before_after_admin_screen`
Start parameter: `src_ig__cmp_sw1__med_reels__cnt_build`
URL: `https://t.me/asknitai_bot?start=src_ig__cmp_sw1__med_reels__cnt_build`

Хук: Мы не делаем магию. Мы каждый день убираем тупые ответы бота.
Название: Build in public

Сцены:
- 0-3с: показать плохой ответ с англо-русской смесью
- 3-8с: показать правило русификации и проверку промптов
- 8-14с: показать новый ответ/картинку/пост
- 14-18с: CTA «следи за каналом и тестируй»

Исходники:
- `assets/stories/product-update-story.png`

Подпись:

```text
Показываем, как Нить становится менее роботской и более полезной: https://t.me/asknitai_bot?start=src_ig__cmp_sw1__med_reels__cnt_build
```

CTA: Следить за разработкой
Модерация: Не раскрывать приватные данные пользователей.

## Day 3: vgw1_payment_meaning

Статус: `draft`
Площадка: `tiktok`
Рубрика: `premium`
Длина: `20 sec`
Формат ассетов: `pricing_overlay_plus_chat`
Start parameter: `src_tt__cmp_sw1__med_sv__cnt_pay`
URL: `https://t.me/asknitai_bot?start=src_tt__cmp_sw1__med_sv__cnt_pay`

Хук: Платить за AI стоит только когда он реально продолжает мысль.
Название: За что платить в Нити

Сцены:
- 0-3с: Free — попробовать стиль
- 3-8с: Pro — больше контекста и режимы
- 8-14с: Premium — глубокие разборы и память
- 14-20с: CTA «сначала попробуй бесплатно»

Исходники:
- `assets/stories/payments-story.png`

Подпись:

```text
Free нужен для первого контакта. Платный доступ — для глубины и контекста: https://t.me/asknitai_bot?start=src_tt__cmp_sw1__med_sv__cnt_pay
```

CTA: Сначала попробуй бесплатно
Модерация: Не обещать гарантированный результат после оплаты.
