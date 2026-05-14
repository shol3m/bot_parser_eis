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
│       └── pages.yml         # автодеплой webapp/ на GitHub Pages
├── cloudflared.exe           # бинарник тоннеля Windows (не в git; на Mac ищется в PATH)
├── docs/                     # техническая документация
├── config/
│   ├── bot_config.json       # токен, chat_id, allowed_users, proxy  ← НЕ В GIT
│   ├── filters.json          # фильтры для daily_run
│   ├── saved_filters.json    # пресеты фильтров бота
│   └── prompts.json          # промпты анализа (detailed, quick)
├── agents/
│   ├── parser_agent.py       # агент парсинга — самостоятельный, CLI + import
│   ├── analyze_agent.py      # агент анализа документов — универсальный, CLI + import
│   └── analyze_tz.py         # устарел, оставлен как бэкап
├── parsers/
│   └── zakupki.py            # низкоуровневый парсер zakupki.gov.ru
├── orchestrator.py           # координирует агентов, вызывается ботом
├── bot/
│   └── bot.py                # Telegram-бот (основной файл)
├── webapp/
│   ├── index.html            # Telegram Mini App (хостится на GitHub Pages)
│   ├── data_{chat_id}.json   # результаты поиска per-user (генерируется, не в git)
│   ├── subs_{chat_id}.json   # подписки per-user (генерируется, не в git)
│   └── config.json           # username бота для Mini App (генерируется, не в git)
├── data/
│   ├── db.py                 # SQLite — data/state.db
│   ├── contracts/            # JSON результатов парсинга
│   └── documents/            # скачанные документы закупок
├── daily_run.py              # оркестратор: парсинг + анализ + дайджест
├── notify.py                 # утилита отправки сообщений в Telegram
└── backup_2026_05_13/        # бэкап файлов до рефакторинга агентов
```

---

## Архитектура

```
bot/bot.py  (Telegram UI + Mini App сервер)
    │
    ├── HTTP-сервер :8742  ──►  cloudflared  ──►  https://xxx.trycloudflare.com
    │       └── data_{chat_id}.json, subs_{chat_id}.json, config.json
    │                                  (только данные — HTML на GitHub Pages)
    │
    ├── GitHub Pages  ──►  https://shol3m.github.io/bot_parser_eis/
    │       └── webapp/index.html  (постоянный URL, не меняется при рестарте)
    │
    ▼
orchestrator.py  (координатор)
    │
    ├──► agents/parser_agent.py  → parsers/zakupki.py
    │         вход:  filters dict
    │         выход: list[dict] закупок
    │
    └──► agents/analyze_agent.py  → claude --print
              вход:  list[Path] документов + prompt str
              выход: str анализа
```

**Как работает Mini App:**
- `index.html` хостится на GitHub Pages — URL постоянный, не меняется при рестарте бота
- Кнопка в боте открывает `https://shol3m.github.io/bot_parser_eis/?api=<tunnel_url>`
- Mini App читает `?api=` параметр и загружает данные с тоннеля
- Данные per-user: каждый видит только свои результаты поиска и подписки
- Если бот офлайн (нет `?api=`) — страница открывается, показывает подсказку

---

## Запуск

```bash
python "d:\agent_system\bot\bot.py"          # бот + Mini App сервер (держать запущенным)
python "d:\agent_system\daily_run.py"        # ручной сбор + анализ + дайджест
python "d:\agent_system\notify.py" "текст"   # отправить сообщение в Telegram

# Агенты напрямую:
python "d:\agent_system\agents\parser_agent.py" --filters config/filters.json
python "d:\agent_system\agents\analyze_agent.py" doc.pdf --prompt "Проанализируй ТЗ..."
```

**Перед запуском бота**: убедиться что Hiddify подключён (порт 12334).
Проверка: `python -c "import httpx,asyncio; asyncio.run(httpx.AsyncClient(proxy='socks5://127.0.0.1:12334', timeout=10).get('https://api.telegram.org'))"` — должно вернуть 302.

**При старте бот автоматически:**
1. Запускает HTTP-сервер на порту 8742 (раздаёт JSON-данные из `webapp/`)
2. Ищет cloudflared: сначала `cloudflared.exe` / `cloudflared` рядом с собой, потом в PATH
3. Поднимает cloudflared тоннель (~10 сек) — передаёт URL как параметр в кнопку Mini App
4. Кнопка «🌐 Открыть в приложении» **всегда видна** (HTML на GitHub Pages), данные доступны когда тоннель работает

---

## Команды бота

| Команда / Кнопка | Что делает |
|---------|-----------|
| `/start` | Регистрация / приветствие. Незнакомый пользователь → запрос владельцу |
| `/help`, `❓ Помощь` | Инструкция |
| `/fetch`, `🔍 Найти закупки` | Поиск закупок с пагинацией ◀ ▶ |
| `/fetch 15.05.2026` | Закупки за конкретную дату |
| `/filters`, `⚙️ Фильтры поиска` | ФЗ, ОКПД2, ключевые слова, сумма, дата, пресеты |
| `/watch`, `🔔 Подписки` | Авто-уведомления при появлении новых закупок |
| `/prompt`, `🤖 Настройки анализа` | Просмотр и редактирование инструкции для Claude |
| `/schedule`, `⏰ Расписание` | Время ежедневного дайджеста (09:00–18:00 МСК) |
| `/status`, `📊 Статус` | Статистика БД + активный пресет |
| `/restart` | Перезапуск бота (только владелец) |
| `/users` | Список пользователей с доступом (только владелец) |
| `/removeuser ID` | Отозвать доступ у пользователя (только владелец) |
| Кнопка "🤖 Анализ" | Выбор документов с ЕИС → анализ через Claude |
| Кнопка "🌐 Открыть в приложении" | Открыть Telegram Mini App с результатами |
| Кнопка "🛑 Остановить" | Остановка поиска (⚠️ баг: не всегда срабатывает, отложено) |

---

## Multi-user доступ

`config/bot_config.json` содержит:
- `chat_id` — владелец (получает дайджесты, управляет расписанием)
- `allowed_users` — список chat_id с доступом
- `pending_users` — ожидают подтверждения

Новый пользователь пишет `/start` → владелец получает уведомление с кнопками **✅ Разрешить / ❌ Отклонить**.

---

## Mini App

Telegram Mini App открывается кнопкой после поиска.

**Вкладки:**
- **Результаты** — карточки закупок, клиентская фильтрация
- **Фильтры** — фильтрация по ключевым словам и цене
- **Подписки** — список активных подписок

**Данные:** бот пишет `webapp/data_{chat_id}.json` после каждого поиска и `webapp/subs_{chat_id}.json` при открытии раздела «Подписки». Каждый пользователь видит только свои данные — файлы не перезаписывают друг друга.

**Анализ из Mini App:** кнопка «🤖 Анализ» закрывает Mini App и открывает бот с командой `/start analyze_ID` — бот запускает полноценный анализ через Claude.

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

- **Кнопка «🛑 Остановить» при поиске** — `future.cancel()` не прерывает запущенный поток.
  Решение: заменить `run_in_executor` на subprocess с `process.terminate()`. Отложено.
- **URL тоннеля меняется при рестарте** — ограничение бесплатного cloudflared quick tunnel.
  Частично решено: HTML на GitHub Pages постоянный, тоннель передаётся как `?api=` параметр.
  Кнопки в старых сообщениях после рестарта будут показывать «Бот не подключён» — нужно запустить новый поиск.
  Полное решение: завести аккаунт Cloudflare и использовать именованный тоннель (`cloudflared tunnel create`).
- **JobQueue недоступен** если установлен `python-telegram-bot` без `[job-queue]` — расписание и подписки не работают.
