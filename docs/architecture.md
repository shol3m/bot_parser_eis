# Архитектура бота

## Общая схема

```
Telegram → bot.py → parsers/zakupki.py → zakupki.gov.ru
                 → agents/analyze_tz.py → claude CLI → Anthropic
                 → data/db.py → data/state.db
```

---

## Ключевые паттерны

### Фильтры и пресеты

| Ключ user_data | Назначение |
|----------------|-----------|
| `draft` | Черновик фильтра, редактируется кнопками в `/filters` |
| `await_input` | Тип ожидаемого текстового ввода (цена / дата / имя пресета / промпт / ключевые слова) |
| `filter_msg_id` | message_id меню фильтров для обновления на месте |
| `pending_filter` | Применённый фильтр, ждёт запуска `/fetch` |

После любого изменения меню обновляется на месте через `_refresh_filter_msg()` / `edit_message_text`.

### Пагинация (`/fetch`)

| Ключ user_data | Назначение |
|----------------|-----------|
| `results` | Список контрактов текущей сессии |
| `pg_idx` | Текущий индекс карточки |

Карточка редактируется на месте (`edit_message_text`). При перезапуске бота `user_data` очищается — нужен новый `/fetch`.

### Детальный анализ

| Ключ user_data | Назначение |
|----------------|-----------|
| `docs_{contract_id}` | Список документов с ЕИС для выбора |
| `sel_{contract_id}` | Set выбранных индексов |
| `sel_msg_{contract_id}` | message_id меню выбора (для удаления) |

Флоу: получить список документов с ЕИС → показать с чекбоксами → скачать выбранные → Claude → результат.

### Мониторинг (`/watch`)

Вотчи хранятся в SQLite (`watches`). При запуске бота все активные вотчи восстанавливаются через `JobQueue.run_repeating()`. Проверка — сравнение номеров закупок с уже известными в БД.

---

## Callback-схема

```
f:law:{44|223|both}     — выбор ФЗ
f:okpd:{J|all|custom}   — выбор раздела ОКПД2
f:kw:{set|clear}        — ключевые слова
f:price_from            — ввод минимальной суммы
f:price_to              — ввод максимальной суммы
f:date:{today|yesterday|custom}  — выбор даты
f:save                  — сохранить пресет
f:presets               — список пресетов
f:apply                 — применить фильтры

ps:load:{name}          — загрузить пресет
ps:del:{name}           — удалить пресет
ps:back                 — назад в меню фильтров

pg:next / pg:prev / pg:skip  — листание карточек

detail:{id}             — запустить детальный анализ
da:toggle:{cid}:{idx}   — переключить выбор документа
da:all:{cid}            — выбрать все документы
da:none:{cid}           — снять все документы
da:run:{cid}            — запустить анализ выбранных

pr:edit                 — редактировать промпт
pr:reset                — сбросить промпт к дефолту

wt:new                  — создать вотч
wt:interval:{h}         — выбрать интервал вотча
wt:info:{id}            — информация о вотче
wt:del:{id}             — удалить вотч
wt:back                 — назад к списку вотчей

sch:{HH:MM}             — установить расписание
sch:off                 — отключить расписание
```

---

## Сетевые особенности

- **Прокси**: Hiddify, `socks5://127.0.0.1:12334` — нужен для Telegram
- **Парсер ЕИС**: работает без прокси (`proxies=None`) — системный прокси ломает TLS с ЕИС
- **SSL патч** (`SECLEVEL=1`) в начале `bot.py` — нужен для Python 3.14 + OpenSSL 3.x
- **HTTPXRequest** через SOCKS5 требует `httpx_kwargs={"verify": False}`
- **`run_polling`** обязательно с `allowed_updates=Update.ALL_TYPES` — иначе Telegram не доставляет `callback_query`
- Таймауты HTTPXRequest: `read=20, write=20, connect=15`

---

## Устойчивость к ошибкам

- `_qanswer(query, text)` — `query.answer()` не падает при сетевых флуктуациях
- Все `edit_message_text` обёрнуты в `try/except (BadRequest, TimedOut, NetworkError)`
- Тяжёлые операции (парсинг, скачивание, Claude) — через `loop.run_in_executor()` чтобы не блокировать event loop
- Запросы к ЕИС с `asyncio.wait_for(..., timeout=30)`
