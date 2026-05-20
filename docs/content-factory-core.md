# Контент-завод

Это слой выше конкретного бота. Его задача: брать любой проект, превращать его в календарь контента, генерировать ассеты, собирать ролики и давать таблицу для публикаций и аналитики.

## Как устроено

```text
config/content_factory.json
  -> список проектов и роли команды

config/<project>_social_video_schedule.json
  -> конкретный календарь проекта

scripts/generate_social_videos.py
  -> универсальный сборщик вертикальных роликов

assets/<project>
  -> исходники, карточки, видео, обложки

docs/*board.csv
  -> производственная доска и метрики
```

Сейчас активный проект один: `Нить`. Но генератор больше не обязан знать, что это именно Telegram-бот. Он берет название, ссылку, handle и папку карточек из `product` внутри schedule-конфига.

## Как подключить новый проект

1. Добавить проект в `config/content_factory.json`.
2. Создать отдельный schedule-файл по образцу `config/social_video_schedule.json`.
3. Указать в нем:

```json
{
  "product": {
    "brand_name": "Название",
    "public_handle": "@handle_or_site",
    "link_label": "Попробовать: @handle_or_site",
    "primary_url_template": "https://example.com/?utm={start_parameter}",
    "source_cards_dir": "assets/new-project/cards/week-01"
  }
}
```

4. Сложить карточки в `source_cards_dir` с именами `card-01.png`, `card-02.png` и так далее.
5. Запустить:

```powershell
python scripts\generate_social_videos.py --config config\new_project_social_video_schedule.json
```

## Команда внутри завода

- Producer: решает, что выпускаем и в каком порядке.
- Copywriter: пишет хуки, подписи и CTA.
- Designer: держит визуальный стиль и карточки.
- Video editor: собирает MP4, обложки и версии под платформы.
- SMM: публикует и ведет комментарии.
- Analyst: смотрит, что привело людей в продукт.

## Почему так лучше

Если завтра мы делаем не бота, а другой SaaS, канал, мини-курс или лендинг, меняется только конфиг проекта и карточки. Скрипты, workflow, доска метрик и правила публикации остаются теми же.
