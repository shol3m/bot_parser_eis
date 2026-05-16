# Конфигурация

Все конфиги хранятся в `config/`. Изменения применяются при следующем использовании (не требуют перезапуска бота, кроме `bot_config.json`).

---

## bot_config.json

Основной конфиг бота. Изменения вступают в силу после `/restart`.

```json
{
  "token": "...",                        // токен Telegram-бота
  "chat_id": 123456789,                  // chat_id владельца (устанавливается /start)
  "proxy": "socks5://127.0.0.1:12334",  // SOCKS5-прокси (Hiddify)
  "schedule_time": "10:00"              // время автосбора МСК (устанавливается /schedule)
}
```

---

## saved_filters.json

Сохранённые фильтры закупок. Управляется через ⚙️ Фильтры поиска → 📋 Фильтры.

```json
{
  "active": "default",
  "presets": {
    "default": {
      "keywords":      [],           // ключевые слова (список строк)
      "okpd2_key":     8873870,      // внутренний код ОКПД2 (null = все)
      "okpd2_section": "J",          // раздел ОКПД2 ("J", "72" и др., null = все)
      "region_codes":  [],           // коды регионов (пока не используются)
      "price_from":    null,         // НМЦ от (руб, число или null)
      "price_to":      null,         // НМЦ до (руб, число или null)
      "law":           "44",         // "44", "223" или "both"
      "methods":       [],           // ["af","ca","pa"] или [] = все способы
      "date_from":     "today",      // "today", "yesterday" или "ДД.ММ.ГГГГ"
      "date_to":       "today",
      "date_type":     "published"   // "published", "updated", "end"
    }
  }
}
```

**Примечания:**
- Фильтр `"default"` нельзя удалить
- `"law": "both"` — два запроса к парсеру, результаты объединяются с дедупликацией по `number`
- `"okpd2_section": null` + `"okpd2_key": null` = поиск по всем разделам
- `"methods": []` = все способы закупки; `["af"]` = только аукционы
- `"customer_inn"` добавляется в `searchString` (ЕИС не принимает его отдельным параметром)

---

## prompts.json

Промпты для Claude. `"detailed"` редактируется через `/prompt` в боте.

```json
{
  "quick":     "...",   // быстрая оценка 1-10, используется в daily_run.py
  "detailed":  "...",   // полный анализ по кнопке Анализ, кешируется в БД
  "sort":      "",      // промпт сортировки (не реализован, поле готово)
  "min_score": 6,       // минимальный балл для дайджеста
  "top_n":     10       // максимум закупок в дайджесте
}
```

Промпты используют плейсхолдер `{documents_text}` — заменяется на извлечённый текст документов. При редактировании через `/prompt` плейсхолдер дописывается автоматически если отсутствует.

---

## filters.json

Фильтры для `daily_run.py` (не для бота). Структура аналогична пресету в `saved_filters.json`.

```json
{
  "keywords":      [],
  "okpd2_key":     8873870,
  "okpd2_section": "J",
  "region_codes":  [],
  "customer_inn":  "",
  "price_from":    null,
  "price_to":      null,
  "law":           "44",
  "methods":       [],
  "date_from":     "today",
  "date_to":       "today",
  "date_type":     "published"
}
```

---

## saved_pp_filters.json

Сохранённые фильтры НМЦК. Управляется через ⚙️ Фильтры поиска (раздел НМЦК) → 📋 Фильтры.  
Структура аналогична `saved_filters.json`. Фильтр `"default"` нельзя удалить.

---

## priceplan_filter.json

Текущий активный фильтр НМЦК (рабочая копия). Перезаписывается при каждом запуске поиска и при загрузке сохранённого фильтра.

```json
{
  "keywords":           [],
  "region_codes":       [],
  "customer_inn":       "",
  "statuses":           ["published", "proposed", "ended", "cancelled"],
  "publish_date_from":  "today",
  "publish_date_to":    "today",
  "update_date_from":   null,
  "update_date_to":     null
}
```

`statuses`: любая комбинация `"published"` / `"proposed"` / `"ended"` / `"cancelled"`.  
Два независимых диапазона дат: `publish_date_from/to` и `update_date_from/to`.  
ОКПД2 не поддерживается разделом pricereq ЕИС.
