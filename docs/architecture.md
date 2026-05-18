# Архитектура бота

## Общая схема

```
Telegram → bot.py → parsers/zakupki.py → zakupki.gov.ru
                 → agents/analyze_tz.py → claude CLI → Anthropic
                 → data/db.py → data/state.db
```

---

## Ключевые паттерны

### Фильтры (двухуровневые меню)

Оба раздела (закупки и НМЦК) используют компактное главное меню: одна кнопка = один параметр с текущим значением. Нажатие открывает подменю с детальным выбором и кнопкой «← Назад».

**Подменю закупок:** ФЗ и способ / ОКПД2 / Дата / Сумма  
**Подменю НМЦК:** Статус / Дата размещения / Дата обновления

| Ключ user_data | Назначение |
|----------------|-----------|
| `draft` | Черновик фильтра закупок |
| `filter_view` | Текущий вид меню: `"main"` / `"law_method"` / `"okpd"` / `"date"` / `"sum"` |
| `filter_msg_id` | message_id меню фильтров (для редактирования на месте) |
| `pending_filter` | Фильтр для ближайшего `/fetch` |
| `pp_draft` | Черновик фильтра НМЦК |
| `pp_filter_view` | Текущий вид меню НМЦК: `"main"` / `"status"` / `"pub_date"` / `"upd_date"` |
| `pp_filter_msg_id` | message_id меню фильтров НМЦК |
| `await_input` | Тип ожидаемого текста: `keywords` / `customer_inn` / `price_from` / `price_to` / `date_range` / `okpd2_code` / `preset_name` / `pp_keywords` / `pp_customer` / `pp_pub_date_range` / `pp_upd_date_range` / `pp_preset_name` / `ppwatch_name` / `prompt_detailed` |

После любого изменения меню обновляется на месте через `_refresh_filter_msg()` / `_pp_refresh()`. Обе функции читают `filter_view` / `pp_filter_view` и рендерят соответствующую клавиатуру через `_get_filter_kb()` / `_get_pp_filter_kb()`.

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

### Mini App (webapp/index.html)

Хостится на GitHub Pages. Бот пушит JSON-файлы через GitHub API после каждого поиска.

**JSON-файлы на GitHub Pages:**

| Файл | Когда обновляется | Содержимое |
|------|-------------------|-----------|
| `data_{chat_id}.json` | После поиска закупок | `contracts[]`, `active_preset`, `active_filter`, `presets[]`, `preset_details{}` |
| `priceplan_{chat_id}.json` | После поиска НМЦК | `contracts[]`, `active_preset`, `active_filter`, `presets[]`, `preset_details{}` |
| `subs_{chat_id}.json` | После поиска / удаления подписки | `[{id, name, interval_h, active, last_run, _type}]` |
| `config.json` | При старте бота | `{bot_username, webapp_url}` |

`_type` в `subs` — `"zakupki"` или `"nmck"` (определяется из `filters_json` в БД).

**sendData-действия (Mini App → бот):**

| action | Поля | Что делает бот |
|--------|------|---------------|
| `search` | `law`, `methods`, `okpd2_section`, `date_type`, `date`, `customer_inn`, `keywords`, `price_from`, `price_to` | Запускает `cmd_fetch` |
| `priceplan_search` | `statuses`, `publish_date_from/to`, `update_date_from/to`, `customer_inn`, `keywords` | Запускает `cmd_priceplan` |
| `analyze` | `contract_id: int` | Запускает `_run_detail_analysis` |
| `watch_delete` | `watch_id: int` | Удаляет подписку, пушит обновлённый `subs_{chat_id}.json` |
| `open_watch` | `section: "zakupki"\|"nmck"` | Открывает меню подписок в чате |

Вспомогательные функции в `bot.py`: `_webapp_build_zakupki_filter()`, `_webapp_build_priceplan_filter()`, `_webapp_resolve_date()`.

---

### Мониторинг (`/watch`)

Вотчи хранятся в SQLite (`watches`). При запуске бота все активные вотчи восстанавливаются через `JobQueue.run_repeating()`. Проверка — сравнение номеров закупок с уже известными в БД.

---

## Callback-схема

```
# Фильтры закупок (главное меню)
f:open:{law_method|okpd|date|sum}  — открыть подменю
f:back                             — вернуться в главное меню
f:law:{44|223|both}                — выбор ФЗ (в подменю)
f:method:{af|ca|pa}                — выбор способа (в подменю)
f:okpd:{J|all|custom}              — выбор ОКПД2 (в подменю)
f:kw:{set|clear}                   — ключевые слова
f:customer:{set|clear}             — заказчик
f:price_from / f:price_to          — ввод суммы (в подменю sum)
f:date_type:{published|updated|end}— тип даты (в подменю date)
f:date:{today|yesterday|week|custom}— выбор даты (в подменю date)
f:save                             — сохранить фильтр (в списке фильтров)
f:presets                          — открыть список сохранённых фильтров
f:reset                            — сбросить всё к дефолту
f:apply                            — запустить поиск с текущими фильтрами

# Сохранённые фильтры закупок
ps:load:{name}  — загрузить фильтр
ps:del:{name}   — удалить фильтр
ps:back         — назад в меню фильтров

# Фильтры НМЦК (главное меню)
ppf:open:{status|pub_date|upd_date} — открыть подменю
ppf:back                             — вернуться в главное меню
ppf:status:{published|proposed|ended|cancelled} — переключить статус
ppf:pub_date:{today|yesterday|week|clear|custom} — дата размещения
ppf:upd_date:{today|yesterday|week|clear|custom} — дата обновления
ppf:kw:{set|clear}                   — ключевые слова
ppf:customer:{set|clear}             — заказчик
ppf:reset                            — сбросить фильтры НМЦК
ppf:run                              — запустить поиск НМЦК
ppf:presets                          — список сохранённых фильтров НМЦК
ppf:save                             — сохранить фильтр НМЦК
ppf:ps_load:{name}                   — загрузить фильтр НМЦК
ppf:ps_del:{name}                    — удалить фильтр НМЦК
ppf:ps_back                          — назад в меню фильтров НМЦК

# Пагинация
pg:next / pg:prev / pg:skip  — листание карточек

# Детальный анализ
detail:{id}             — запустить детальный анализ
da:toggle:{cid}:{idx}   — переключить выбор документа
da:all:{cid}            — выбрать все документы
da:none:{cid}           — снять все документы
da:run:{cid}            — запустить анализ выбранных

# Промпт
pr:edit   — редактировать промпт
pr:reset  — сбросить промпт к дефолту

# Подписки закупок
wt:new           — создать подписку
wt:interval:{h}  — выбрать интервал
wt:info:{id}     — информация о подписке
wt:del:{id}      — удалить подписку
wt:back          — назад к списку

# Подписки НМЦК
ppwt:new           — создать подписку (→ ввод имени → ppwt:interval)
ppwt:interval:{h}  — выбрать интервал
ppwt:info:{id}     — информация о подписке
ppwt:del:{id}      — удалить подписку
ppwt:back          — назад к списку

# Расписание
sch:{HH:MM} / sch:off     — расписание закупок
schpp:{HH:MM} / schpp:off — расписание НМЦК
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
