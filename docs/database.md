# База данных

SQLite, файл: `data/state.db`. Инициализация: `data/db.py → init_db()`.

---

## Таблица `contracts`

Основное хранилище закупок.

```sql
CREATE TABLE contracts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    number        TEXT UNIQUE,       -- номер закупки на ЕИС
    subject       TEXT,              -- предмет контракта
    price         TEXT,              -- НМЦ (строка, как на сайте)
    customer      TEXT,              -- заказчик
    url           TEXT,              -- ссылка на карточку ЕИС
    date_found    TEXT,              -- дата добавления (date('now'))
    quick_score   INTEGER,           -- оценка 1-10 от Claude (quick-анализ)
    quick_comment TEXT,              -- краткий комментарий Claude
    docs_dir      TEXT,              -- путь к папке со скачанными документами
    detail_text   TEXT,              -- кешированный детальный анализ (Claude)
    tg_message_id INTEGER            -- id сообщения дайджеста в Telegram
);
```

**Примечания:**
- `number` уникален — повторный upsert обновляет только `subject` и `price`
- `detail_text` кешируется: повторный нажим "🔍 Анализ" отдаёт сохранённый результат
- `docs_dir` заполняется при скачивании документов через бот или `daily_run.py`

---

## Таблица `watches`

Активные мониторинги пользователя.

```sql
CREATE TABLE watches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,        -- название (имя пресета фильтров)
    filters_json TEXT NOT NULL,        -- JSON с фильтрами
    interval_h   INTEGER NOT NULL,     -- интервал проверки в часах
    chat_id      INTEGER NOT NULL,     -- Telegram chat_id владельца
    active       INTEGER NOT NULL DEFAULT 1,  -- 1 = активен
    last_run     TEXT                  -- datetime последней проверки
);
```

**Логика проверки:**
1. `JobQueue.run_repeating()` запускает `_watch_check_job` каждые `interval_h` часов
2. Парсер ищет закупки по сохранённым фильтрам
3. Каждый результат проверяется: есть ли `number` в таблице `contracts`
4. Новые — добавляются в БД и отправляются уведомлением в Telegram
5. `last_run` обновляется после каждой проверки

---

## Основные функции db.py

| Функция | Назначение |
|---------|-----------|
| `init_db()` | Создание таблиц если не существуют |
| `upsert_contract(data)` | Добавить или обновить закупку, вернуть id |
| `get_contract(id)` | Получить закупку по id |
| `update_detail(id, text)` | Сохранить результат детального анализа |
| `update_quick(id, score, comment, docs_dir)` | Сохранить quick-оценку |
| `get_top_contracts(min_score, top_n)` | Топ закупок за сегодня для дайджеста |
| `add_watch(name, filters, interval_h, chat_id)` | Создать вотч |
| `list_watches(chat_id)` | Список вотчей пользователя |
| `delete_watch(id)` | Удалить вотч |
| `touch_watch(id)` | Обновить `last_run` |
| `get_all_active_watches()` | Все активные вотчи (для восстановления при рестарте) |
