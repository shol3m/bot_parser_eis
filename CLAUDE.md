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
│   ├── priceplan_filter.json # текущий активный фильтр НМЦК (рабочая копия)
│   ├── saved_filters.json    # сохранённые фильтры бота (закупки)
│   ├── saved_pp_filters.json # сохранённые фильтры бота (НМЦК)
│   └── prompts.json          # промпты анализа (detailed, quick)
├── agents/
│   ├── parser_agent.py       # агент парсинга закупок — CLI (--filters, --out) + import
│   ├── priceplan_agent.py    # агент парсинга НМЦК — CLI + import
│   ├── analyze_agent.py      # агент анализа документов — универсальный, CLI + import
│   └── analyze_tz.py         # устарел, оставлен как бэкап
├── parsers/
│   ├── zakupki.py            # парсер основного раздела zakupki.gov.ru
│   └── priceplan.py          # парсер раздела pricereq (НМЦК)
├── orchestrator.py           # координирует агентов: fetch_contracts, fetch_priceplan, analyze_contract
├── bot/
│   └── bot.py                # Telegram-бот (основной файл)
├── webapp/
│   ├── index.html            # Telegram Mini App v2 (хостится на GitHub Pages)
│   ├── data_{chat_id}.json   # результаты поиска закупок per-user (генерируется)
│   ├── priceplan_{chat_id}.json  # результаты НМЦК per-user (генерируется)
│   ├── subs_{chat_id}.json   # подписки per-user (генерируется)
│   └── config.json           # username бота и webapp_url (генерируется)
├── data/
│   ├── db.py                 # SQLite — data/state.db
│   ├── contracts/            # JSON результатов парсинга
│   ├── documents/            # скачанные документы закупок
│   └── debug_priceplan.html  # HTML первой страницы pricereq для отладки селекторов
├── daily_run.py              # оркестратор: парсинг + анализ + дайджест (закупки)
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
    │         вход:  filters dict (НМЦК)
    │         выход: list[dict] запросов цены
    │
    └──► agents/analyze_agent.py  → Groq API (llama-3.3-70b-versatile)
              вход:  list[Path] документов + prompt str
              выход: str анализа
```

**Как работает поиск закупок:**
- `cmd_fetch` запускает `parser_agent.py` как **subprocess** (`asyncio.create_subprocess_exec`)
- Прогресс читается из stdout процесса и обновляет статусное сообщение
- Кнопка «🛑 Остановить» вызывает `proc.terminate()` — мгновенная остановка
- Результаты записываются в temp-файл (`--out`), читаются после завершения

**Как работает поиск НМЦК:**
- `cmd_priceplan` запускает `fetch_priceplan` в `asyncio.run_in_executor`
- Прогресс обновляется через `progress_cb` → `asyncio.run_coroutine_threadsafe`
- Жёсткий таймаут 120 секунд, лимит `max_pages=10` для интерактивного поиска
- Кнопка «🛑 Остановить» устанавливает `stop_event`

**Как работает Mini App (v3):**
- `webapp/index.html` хостится на **GitHub Pages** (постоянный URL, без тоннелей)
- Глобальный переключатель раздела **Закупки / НМЦК** в шапке — синхронизирует все три вкладки
- **Вкладки:** Результаты · Фильтры · Подписки
- **Фильтры Закупки:** ФЗ, способ (ЭА/Конкурс/ЗП), ОКПД2, тип даты, период, заказчик, ключевые слова, цена
- **Фильтры НМЦК:** статусы (мультиселект), дата публикации, дата обновления, заказчик, ключевые слова
- **Сохранённые фильтры:** чипы загружаются из JSON (`preset_details`), клик применяет пресет в форму
- **Подписки:** список с кнопкой 🗑 удалить (через `sendData`) и «+ Создать» (открывает бот)
- Фильтры сохраняются в `localStorage` между сессиями
- Запуск поиска → `tg.sendData()` → бот ищет → пушит JSON на GitHub → присылает кнопку «📱 Открыть результаты»
- Данные per-user: `data_{chat_id}.json`, `priceplan_{chat_id}.json`, `subs_{chat_id}.json`

**sendData-действия из Mini App:**

| action | Что делает |
|--------|-----------|
| `search` | Поиск закупок. Поля: `law`, `methods`, `okpd2_section`, `date_type`, `date`, `customer_inn`, `keywords`, `price_from`, `price_to` |
| `priceplan_search` | Поиск НМЦК. Поля: `statuses`, `publish_date_from/to`, `update_date_from/to`, `customer_inn`, `keywords` |
| `analyze` | Анализ закупки. Поля: `contract_id` (int) |
| `watch_delete` | Удалить подписку. Поля: `watch_id` (int) |
| `open_watch` | Открыть меню подписок в боте. Поля: `section` (`"zakupki"` или `"nmck"`) |

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

**Важно:** не запускать более одного экземпляра бота — будет конфликт `getUpdates`.

---

## Навигация бота (двухуровневое меню)

**Главное меню:**
```
[📋 Закупки]  [💰 НМЦК]
[❓ Помощь]   [🌐 Приложение]
```

**Раздел Закупки** (своя клавиатура):
```
[🔍 Найти закупки]
[⚙️ Фильтры поиска]  [🔔 Подписки]
[⏰ Расписание]       [❓ Помощь]
[← Главное меню]
```

**Раздел НМЦК** (своя клавиатура):
```
[💰 Найти НМЦК]
[⚙️ Фильтры поиска]  [🔔 Подписки]
[⏰ Расписание]       [❓ Помощь]
[← Главное меню]
```

Кнопки «⚙️ Фильтры поиска», «🔔 Подписки», «⏰ Расписание» одинаковые в обоих разделах — бот диспетчеризует по `context.user_data["section"]` (`"zakupki"` или `"nmck"`).

---

## Команды бота

| Команда / Кнопка | Что делает |
|---------|-----------|
| `/start` | Регистрация / приветствие. Незнакомый пользователь → запрос владельцу |
| `/help`, `❓ Помощь` | Инструкция |
| `/fetch`, `🔍 Найти закупки` | Поиск закупок с пагинацией ◀ ▶ |
| `/fetch 15.05.2026` | Закупки за конкретную дату |
| `/filters`, `⚙️ Фильтры поиска` (раздел Закупки) | Компактное двухуровневое меню: ФЗ+способ / ОКПД2 / Дата / Сумма / Слова / Заказчик. 📋 Фильтры → список сохранённых. |
| `/watch`, `🔔 Подписки` (раздел Закупки) | Авто-уведомления по закупкам |
| `/schedule`, `⏰ Расписание` (раздел Закупки) | Время ежедневного дайджеста закупок |
| `/priceplan`, `💰 Найти НМЦК` | Поиск в разделе «Запросы цены» (pricereq) |
| `/ppfilters`, `⚙️ Фильтры поиска` (раздел НМЦК) | Компактное двухуровневое меню: Статус / Дата размещения / Дата обновления / Слова / Заказчик. 📋 Фильтры → список сохранённых. |
| `/watch_pp`, `🔔 Подписки` (раздел НМЦК) | Авто-уведомления по запросам цены. При создании запрашивает имя подписки. |
| `/schedule_pp`, `⏰ Расписание` (раздел НМЦК) | Время ежедневного дайджеста НМЦК |
| `/prompt` | Просмотр и редактирование инструкции для Claude |
| `/status` | Статистика БД + активный фильтр |
| `/restart` | Перезапуск бота (только владелец) |
| `/users` | Список пользователей с доступом (только владелец) |
| `/removeuser ID` | Отозвать доступ у пользователя (только владелец) |
| Кнопка «🤖 Анализ» | Выбор документов с ЕИС → анализ через Claude |
| Кнопка «🌐 Приложение» | Открыть Telegram Mini App |
| Кнопка «🛑 Остановить» | Немедленная остановка поиска |

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

`date_type`: `"published"` (по размещению) | `"updated"` (по обновлению) | `"end"` (по окончанию подачи заявок).
`methods`: список из `["af","ca","pa"]` — Аукцион / Конкурс / Запрос предложений. Пустой список = все методы.
`customer_inn`: ИНН или наименование заказчика. **Добавляется в `searchString`** (ЕИС игнорирует отдельный параметр — требует внутренний `customerIdOrg` из модалки).
`okpd2_key`: внутренний числовой ID ЕИС. Раздел J = `8873870`. Кастомный код добавляется в `searchString`.

## Фильтры НМЦК (запросы цены)

Раздел: `https://zakupki.gov.ru/epz/pricereq/search/results.html`
ОКПД2 **не поддерживается** этим разделом ЕИС.

Структура (`priceplan_filter.json`):

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

`statuses`: `"published"` (Размещён) | `"proposed"` (Подача предложений) | `"ended"` (Завершён) | `"cancelled"` (Отменён). Любая комбинация.

**Два независимых диапазона дат** — как на сайте ЕИС:
- `publish_date_from/to` → `publishDateFrom/To` (дата размещения)
- `update_date_from/to` → `updateDateFrom/To` (дата обновления)
- Оба можно задать одновременно

`customer_inn`: **добавляется в `searchString`** (ЕИС pricereq не имеет отдельного параметра для заказчика — только `customerPlace` для региона). Поиск морфологический (`morphology=on`).

**Карточка НМЦК** показывает:
- Статус, предмет, заказчик
- 📅 Дата размещения, 🔄 Дата обновления
- ⏳ Приём предложений (парсится из `div.data-block`, поле `date_end`)

**Подписки НМЦК** хранятся в той же таблице `watches` с признаком `_type: "priceplan"` в `filters_json`.
**Расписание НМЦК** хранится в `bot_config.json` как `schedule_pp_time`, запускает `_daily_pp_job`.

---

## Multi-user доступ

`config/bot_config.json` содержит:
- `chat_id` — владелец (получает дайджесты, управляет расписанием)
- `allowed_users` — список chat_id с доступом
- `pending_users` — ожидают подтверждения
- `github_token` — PAT токен для пуша данных на GitHub Pages (scope: `repo`)
- `schedule_time` — время ежедневного дайджеста закупок (МСК)
- `schedule_pp_time` — время ежедневного дайджеста НМЦК (МСК)

Новый пользователь пишет `/start` → владелец получает уведомление с кнопками **✅ Разрешить / ❌ Отклонить**.

---

## Mini App

Telegram Mini App: **https://shol3m.github.io/bot_parser_eis**

Открывается кнопкой «🌐 Приложение» в главном меню.

**Вкладки:**
- **Результаты** — карточки закупок с датами (размещение, обновление, дедлайн), сортировка чипами (рейтинг / цена / дата), клиентская фильтрация, переключатель «Закупки | Запросы цены», кнопка ↻ обновить
- **Фильтры** — два раздела (закупки / запросы цены), настройка ФЗ / ОКПД2 / даты / ключевых слов / цены, сохранение в `localStorage`, кнопка «🔍 Запустить поиск» → `sendData` → бот запускает поиск
- **Подписки** — список активных подписок

---

## Автозапуск

| Что | Когда | Как |
|-----|-------|-----|
| Бот (Windows) | При логине в Windows | `Startup\AgentBot.bat` → `python bot\bot.py` |
| Бот (VPS) | При старте сервера / падении | `systemd` сервис `bot-parser-eis` |
| Дайджест закупок | По расписанию из бота | `JobQueue` `daily_fetch` внутри bot.py (МСК) |
| Дайджест НМЦК | По расписанию из бота | `JobQueue` `daily_pp` внутри bot.py (МСК) |

**Требование:** `python-telegram-bot[job-queue]` для расписания и подписок.
Установка: `pip install "python-telegram-bot[job-queue]"`

---

## Деплой на VPS (Ubuntu)

Схема: `/opt/bot_parser_eis/` + systemd + GitHub Actions автодеплой при пуше в `main`.

**Расположение на сервере:**
```
/opt/bot_parser_eis/
├── venv/                        # виртуальное окружение Python
├── .env                         # TELEGRAM_BOT_TOKEN, GROQ_API_KEY, GITHUB_TOKEN, CHAT_ID
├── config/
│   └── bot_config.json          # токен, chat_id, allowed_users, schedule (НЕ в git)
└── data/
    ├── state.db                 # SQLite база (создаётся через init_db())
    └── documents/               # скачанные документы закупок
```

---

### Первичная установка на чистый Ubuntu VPS

```bash
ssh root@<VPS_IP>

# 1. Системные зависимости
apt update && apt install -y python3-pip python3-venv python3-dev \
    libxml2-dev libxslt1-dev zlib1g-dev git

# 2. Клонировать репо
cd /opt
git clone https://github.com/shol3m/bot_parser_eis.git
cd bot_parser_eis

# 3. Виртуальное окружение и зависимости
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# 4. Создать .env
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=вставить_токен
GROQ_API_KEY=вставить_ключ
GITHUB_TOKEN=вставить_pat_токен
CHAT_ID=вставить_chat_id
EOF

# 5. Создать config/bot_config.json
cat > config/bot_config.json << 'EOF'
{
  "token": "вставить_токен",
  "chat_id": 0,
  "allowed_users": [],
  "proxy": null,
  "github_token": "вставить_pat_токен"
}
EOF
# Заменить 0 на реальный chat_id, вставить токены

# 6. Создать папки данных
mkdir -p data/documents data/contracts

# 7. Создать systemd-сервис
cat > /etc/systemd/system/bot-parser-eis.service << 'EOF'
[Unit]
Description=Bot Parser EIS
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bot_parser_eis
EnvironmentFile=/opt/bot_parser_eis/.env
ExecStart=/opt/bot_parser_eis/venv/bin/python bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bot-parser-eis
systemctl start bot-parser-eis

# 8. Проверить что запустился
systemctl status bot-parser-eis
journalctl -u bot-parser-eis -n 30
```

---

### Настройка автодеплоя (GitHub Actions)

В репозитории уже есть `.github/workflows/deploy.yml`. Нужно добавить два секрета в GitHub → Settings → Secrets → Actions:

| Secret | Значение |
|--------|---------|
| `VPS_HOST` | IP-адрес сервера |
| `SSH_PRIVATE_KEY` | Приватный SSH-ключ для root |

После этого каждый `git push origin main` автоматически деплоит код на VPS.

Генерация ключа (если нет):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/vps_bot -N ""
ssh-copy-id -i ~/.ssh/vps_bot.pub root@<VPS_IP>
cat ~/.ssh/vps_bot  # скопировать в SSH_PRIVATE_KEY на GitHub
```

---

### Управление сервисом

```bash
ssh root@<VPS_IP>

systemctl status bot-parser-eis     # статус
journalctl -u bot-parser-eis -f     # логи в реальном времени
systemctl restart bot-parser-eis    # перезапуск
systemctl stop bot-parser-eis       # остановить
systemctl start bot-parser-eis      # запустить
```

---

### Обновление кода вручную

```bash
cd /opt/bot_parser_eis
git pull origin main
venv/bin/pip install -q -r requirements.txt
systemctl restart bot-parser-eis
```

---

### Полное удаление

```bash
systemctl stop bot-parser-eis
systemctl disable bot-parser-eis
rm -rf /opt/bot_parser_eis
rm /etc/systemd/system/bot-parser-eis.service
systemctl daemon-reload
```

---

### ⚠️ Ограничения в зависимости от локации сервера

| Локация VPS | zakupki.gov.ru | Groq API | Telegram |
|-------------|---------------|----------|----------|
| Зарубежный (EU/US) | ❌ заблокирован | ✅ работает | ✅ работает |
| Российский | ✅ работает | ⚠️ может быть заблокирован | ✅ работает |

**Зарубежный VPS + российский прокси только для парсинга** — оптимальная схема:
прописать `ZAKUPKI_PROXY=socks5://user:pass@host:1080` в `.env`.
Приоритет: `ZAKUPKI_PROXY` из `.env` → `proxy` из `bot_config.json`.

---

## Зависимости

```
python-telegram-bot[job-queue]  requests[socks]  beautifulsoup4  lxml
pdfplumber  python-docx  openpyxl  httpx[socks]  groq  python-dotenv
```

Все зависимости перечислены в `requirements.txt` в корне проекта.

## AI-анализ документов

Вместо Claude CLI (`claude --print`) используется **Groq API** (модель `llama-3.3-70b-versatile`).
- Ключ задаётся через переменную окружения `GROQ_API_KEY` (или `.env` файл).
- Функции-обёртки: `_run_claude` в `agents/analyze_agent.py`, `run_claude` в `daily_run.py` — сигнатуры не изменились.
- `agents/analyze_tz.py` — мёртвый код (не импортируется нигде), также мигрирован на Groq.

## Конфигурация на VPS

Создать `.env` в корне проекта (по образцу `.env.example`):
```
TELEGRAM_BOT_TOKEN=...
GROQ_API_KEY=...
GITHUB_TOKEN=...
CHAT_ID=...
```
Файл `.env` — в `.gitignore`. Загружается автоматически через `python-dotenv` при старте `bot/bot.py` и `daily_run.py`.

---

## Известные баги

- **Раздел НМЦК (pricereq)** — парсер сохраняет `data/debug_priceplan.html` при каждом первом запросе. Если карточки не парсятся — смотреть этот файл и корректировать `parse_priceplan_results()`.
- **Заказчик в НМЦК** — ЕИС pricereq не имеет серверного фильтра по заказчику (только `customerPlace` для региона). Имя заказчика добавляется в `searchString` с `morphology=on`.
- **Способ закупки `pc` (Запрос котировок)** — ЕИС игнорирует `pc=on` в прямых URL-запросах. Кнопка убрана из интерфейса. Другие методы (`af`, `ca`, `pa`) работают корректно.
- **ОКПД2 кастомные коды** — ЕИС не принимает текстовые коды без числового ID. При вводе кода вручную он добавляется в `searchString`. Раздел J (`okpd2Ids=8873870`) работает корректно.
- **Groq API недоступен** если `GROQ_API_KEY` не задан в `.env` или переменных окружения — анализ документов вернёт ошибку, парсинг продолжит работать.
- **JobQueue недоступен** если установлен `python-telegram-bot` без `[job-queue]` — расписание и подписки не работают.
- **Mini App не обновляется без `github_token`** — если в `bot_config.json` не задан `github_token`, бот не пушит JSON на GitHub Pages после поиска. Mini App будет показывать устаревшие данные. Решение: добавить Personal Access Token с правом `contents: write`.
- **Python 3.8 совместимость (Mac/Linux)** — бот разработан под Python 3.9+. На Python 3.8 нужны: `from __future__ import annotations` во всех модулях, убрать `encoding=` из `logging.basicConfig()`, использовать `Optional[X]` вместо `X | None`. Уже исправлено в кодовой базе.

---

## Завершение рабочей сессии

Когда пользователь говорит, что завершает сессию (например, «всё», «заканчиваем», «на сегодня», «стоп»), Claude выполняет:

1. **Обновляет всю необходимую документацию** — CLAUDE.md и все файлы в `docs/`, которые затронуты изменениями сессии (структура, баги, команды, архитектура)
2. **Коммит** — фиксирует все изменённые файлы с осмысленным сообщением
3. **Пуш** — отправляет в `origin/main` (с `pull --rebase` если нужно)
