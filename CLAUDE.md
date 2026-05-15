# Агентная система госзакупок

## Что это

Персональный инструмент для мониторинга госзакупок (44-ФЗ / 223-ФЗ).
Парсит zakupki.gov.ru, анализирует документы через Claude CLI, отправляет результаты в Telegram.

**Владелец**: IT project manager, специализация — госзакупки 44-ФЗ, цифровые проекты.

---

## Структура проекта

```
D:\agent_system\
├── CLAUDE.md                 # этот файл
├── .gitignore                # bot_config.json, state.db, logs не в git
├── .github/
│   └── workflows/
│       └── pages.yml         # автодеплой webapp/ на GitHub Pages при пуше
├── docs/                     # техническая документация
├── config/
│   ├── bot_config.json       # токен, chat_id, allowed_users, proxy, github_token  ← НЕ В GIT
│   ├── filters.json          # фильтры для daily_run (закупки)
│   ├── priceplan_filter.json # фильтры для раздела «Запросы цены»
│   ├── saved_filters.json    # пресеты фильтров бота
│   └── prompts.json          # промпты анализа (detailed, quick)
├── agents/
│   ├── parser_agent.py       # агент парсинга закупок — CLI (--filters, --out) + import
│   ├── priceplan_agent.py    # агент парсинга запросов цены — CLI + import
│   ├── analyze_agent.py      # агент анализа документов — универсальный, CLI + import
│   └── analyze_tz.py         # устарел, оставлен как бэкап
├── parsers/
│   ├── zakupki.py            # парсер основного раздела zakupki.gov.ru
│   └── priceplan.py          # парсер раздела «Планирование → Запросы цены»
├── orchestrator.py           # координирует агентов: fetch_contracts, fetch_priceplan, analyze_contract
├── bot/
│   └── bot.py                # Telegram-бот (основной файл)
├── webapp/
│   ├── index.html            # Telegram Mini App v2 (хостится на GitHub Pages)
│   ├── data_{chat_id}.json   # результаты поиска закупок per-user (генерируется)
│   ├── priceplan_{chat_id}.json  # результаты запросов цены per-user (генерируется)
│   ├── subs_{chat_id}.json   # подписки per-user (генерируется)
│   └── config.json           # username бота и webapp_url (генерируется)
├── data/
│   ├── db.py                 # SQLite — data/state.db
│   ├── contracts/            # JSON результатов парсинга
│   ├── documents/            # скачанные документы закупок
│   └── debug_priceplan.html  # HTML первой страницы priceplan для отладки селекторов
├── daily_run.py              # оркестратор: парсинг + анализ + дайджест
├── notify.py                 # утилита отправки сообщений в Telegram
└── backup_2026_05_13/        # бэкап файлов до рефакторинга агентов
```

---

## Архитектура

```
bot/bot.py  (Telegram UI)
    │
    ├── После поиска → пушит data_{chat_id}.json / priceplan_{chat_id}.json на GitHub API
    │                           ↓
    │              GitHub Pages (постоянный URL, без туннелей)
    │              https://shol3m.github.io/bot_parser_eis
    │
    ▼
orchestrator.py  (координатор)
    │
    ├──► agents/parser_agent.py   → parsers/zakupki.py
    │         вход:  filters dict (закупки)
    │         выход: list[dict] закупок
    │
    ├──► agents/priceplan_agent.py → parsers/priceplan.py
    │         вход:  filters dict (запросы цены)
    │         выход: list[dict] запросов цены
    │
    └──► agents/analyze_agent.py  → claude --print
              вход:  list[Path] документов + prompt str
              выход: str анализа
```

**Как работает поиск из бота:**
- `cmd_fetch` запускает `parser_agent.py` как **subprocess** (`asyncio.create_subprocess_exec`)
- Прогресс читается из stdout процесса и обновляет статусное сообщение
- Кнопка «🛑 Остановить» вызывает `proc.terminate()` — мгновенная остановка
- Результаты записываются в temp-файл (`--out`), читаются после завершения

**Как работает Mini App:**
- `webapp/index.html` хостится на **GitHub Pages**
- Два раздела: «🔍 Закупки» и «💰 Запросы цены» — переключаются в обеих вкладках
- Фильтры сохраняются в `localStorage` между сессиями
- Кнопка «Запустить поиск» → `tg.sendData()` → бот получает фильтры, запускает поиск
- После поиска бот пушит JSON и отправляет уведомление с кнопкой «📱 Открыть результаты»
- Данные per-user: каждый пользователь видит только свои результаты

---

## Запуск

```bash
python "d:\agent_system\bot\bot.py"          # бот (держать запущенным)
python "d:\agent_system\daily_run.py"        # ручной сбор + анализ + дайджест
python "d:\agent_system\notify.py" "текст"   # отправить сообщение в Telegram

# Агенты напрямую:
python "d:\agent_system\agents\parser_agent.py" --filters config/filters.json --out results.json
python "d:\agent_system\agents\priceplan_agent.py" --filters config/priceplan_filter.json
python "d:\agent_system\agents\analyze_agent.py" doc.pdf --prompt "Проанализируй ТЗ..."
```

**Перед запуском бота**: убедиться что Hiddify подключён (порт 12334).
Проверка: `python -c "import httpx,asyncio; asyncio.run(httpx.AsyncClient(proxy='socks5://127.0.0.1:12334', timeout=10).get('https://api.telegram.org'))"` — должно вернуть 302.

**При старте бот автоматически:**
1. Устанавливает `WEBAPP_URL = https://shol3m.github.io/bot_parser_eis`
2. Получает username бота и пушит `webapp/config.json` на GitHub
3. Кнопка «🌐 Приложение» доступна сразу в главном меню

**Важно:** не запускать более одного экземпляра бота — будет конфликт `getUpdates`.

---

## Команды бота

| Команда / Кнопка | Что делает |
|---------|-----------|
| `/start` | Регистрация / приветствие. Незнакомый пользователь → запрос владельцу |
| `/help`, `❓ Помощь` | Инструкция |
| `/fetch`, `🔍 Найти закупки` | Поиск закупок с пагинацией ◀ ▶ |
| `/fetch 15.05.2026` | Закупки за конкретную дату |
| `/priceplan`, `💰 Запросы цены` | Поиск в разделе «Запросы цен товаров, работ, услуг» (pricereq) |
| `/ppfilters` | Настройка фильтров раздела «Запросы цены» |
| `/filters`, `⚙️ Фильтры поиска` | ФЗ, способ закупки, ОКПД2, ключевые слова, заказчик, тип даты, сумма, пресеты |
| `/watch`, `🔔 Подписки` | Авто-уведомления при появлении новых закупок |
| `/prompt` | Просмотр и редактирование инструкции для Claude |
| `/schedule`, `⏰ Расписание` | Время ежедневного дайджеста (09:00–18:00 МСК) |
| `/status` | Статистика БД + активный пресет |
| `/restart`, `♻️ Перезапуск` | Перезапуск бота (только владелец) |
| `/users` | Список пользователей с доступом (только владелец) |
| `/removeuser ID` | Отозвать доступ у пользователя (только владелец) |
| Кнопка «🤖 Анализ» | Выбор документов с ЕИС → анализ через Claude |
| Кнопка «🌐 Приложение» | Открыть Telegram Mini App |
| Кнопка «🛑 Остановить» | Немедленная остановка поиска (`proc.terminate()`) |

---

## Фильтры закупок

Структура фильтра (`saved_filters.json`, `filters.json`):

```json
{
  "keywords":      [],
  "okpd2_key":     8873870,
  "okpd2_section": "J",
  "okpd2_custom_code": null,
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

`date_type`: `"published"` (по размещению) | `"updated"` (по обновлению) | `"end"` (по окончанию подачи заявок → `applSubmissionCloseDateFrom/To`).
`methods`: список из `["af","ca","pa"]` — Аукцион / Конкурс / Запрос предложений. Пустой список = все методы.
`customer_inn`: ИНН или наименование заказчика. **Добавляется в `searchString`** (ЕИС игнорирует `customerFullNameOrinn` в расширенном поиске — требует внутренний `customerIdOrg` из модалки).
`okpd2_key`: внутренний числовой ID ЕИС. Раздел J = `8873870`. Текстовые коды ОКПД2 не работают как отдельный параметр — при вводе кастомного кода он добавляется в `searchString`.

## Фильтры запросов цены

Раздел: `https://zakupki.gov.ru/epz/pricereq/search/results.html` (НЕ priceplan).  
ОКПД2 **не поддерживается** этим разделом ЕИС.

Структура (`priceplan_filter.json`):

```json
{
  "keywords":      [],
  "region_codes":  [],
  "customer_inn":  "",
  "statuses":      ["published", "proposed", "ended"],
  "date_from":     "today",
  "date_to":       "today",
  "date_type":     "published"
}
```

`statuses`: `"published"` (Опубликован) | `"proposed"` (Предложения поданы) | `"ended"` (Завершён). Любая комбинация.
`date_type`: `"published"` | `"updated"` → `publishDateFrom/To` или `updateDateFrom/To`.

---

## Multi-user доступ

`config/bot_config.json` содержит:
- `chat_id` — владелец (получает дайджесты, управляет расписанием)
- `allowed_users` — список chat_id с доступом
- `pending_users` — ожидают подтверждения
- `github_token` — PAT токен для пуша данных на GitHub Pages (scope: `repo`)

Новый пользователь пишет `/start` → владелец получает уведомление с кнопками **✅ Разрешить / ❌ Отклонить**.

---

## Mini App

Telegram Mini App: **https://shol3m.github.io/bot_parser_eis**

Открывается кнопкой «🌐 Приложение» в главном меню.

**Вкладки:**
- **Результаты** — карточки закупок с датами (размещение, обновление, дедлайн), сортировка чипами (рейтинг / цена / дата), клиентская фильтрация, переключатель «Закупки | Запросы цены», кнопка ↻ обновить
- **Фильтры** — два раздела (закупки / запросы цены), настройка ФЗ / ОКПД2 / даты / ключевых слов / цены, сохранение в `localStorage`, кнопка «🔍 Запустить поиск» → `sendData` → бот запускает поиск
- **Подписки** — список активных подписок

**Флоу поиска из Mini App:**
1. Настраиваем фильтры → «Запустить поиск» → экран «Поиск запущен...» → приложение закрывается
2. Бот запускает поиск, пушит результаты на GitHub Pages
3. Бот присылает уведомление «✅ Найдено N закупок [📱 Открыть результаты]»
4. Нажимаем → Mini App открывается с новыми данными

---

## Автозапуск

| Что | Когда | Как |
|-----|-------|-----|
| Бот | При логине в Windows | `Startup\AgentBot.bat` → `python bot\bot.py` |
| Сбор + дайджест | По расписанию из бота | `JobQueue` внутри bot.py (МСК) |

**Требование:** `python-telegram-bot[job-queue]` для расписания и подписок.
Установка: `pip install "python-telegram-bot[job-queue]"`

---

## Зависимости

```
python-telegram-bot[job-queue]  requests  beautifulsoup4  lxml
pdfplumber  python-docx  openpyxl  httpx[socks]
```

---

## Известные баги

- **Раздел «Запросы цены» (pricereq)** — парсер сохраняет `data/debug_priceplan.html` при каждом первом запросе. Если карточки не парсятся — смотреть этот файл и корректировать `parse_priceplan_results()`.
- **Способ закупки `pc` (Запрос котировок)** — ЕИС игнорирует `pc=on` в прямых URL-запросах. Кнопка убрана из интерфейса. Другие методы (`af`, `ca`, `pa`) работают корректно.
- **ОКПД2 кастомные коды** — ЕИС не принимает текстовые коды (`okpd2IdsCodes`) без числового ID. При вводе кода вручную он добавляется в `searchString` как ключевое слово. Раздел J (`okpd2Ids=8873870`) работает корректно.
- **JobQueue недоступен** если установлен `python-telegram-bot` без `[job-queue]` — расписание и подписки не работают.

---

## Завершение рабочей сессии

Когда пользователь говорит, что завершает сессию (например, «всё», «заканчиваем», «на сегодня», «стоп»), Claude выполняет:

1. **Обновляет всю необходимую документацию** — CLAUDE.md и все файлы в `docs/`, которые затронуты изменениями сессии (структура, баги, команды, архитектура)
2. **Коммит** — фиксирует все изменённые файлы с осмысленным сообщением
3. **Пуш** — отправляет в `origin/main` (с `pull --rebase` если нужно)
