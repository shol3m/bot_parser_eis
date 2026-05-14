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
    ├── HTTP-сервер :8742  ──►  ngrok (постоянный)  ──►  https://xxx.ngrok-free.app
    │       └── webapp/index.html, data_{chat_id}.json, subs_{chat_id}.json
    │                              (или cloudflared quick tunnel как fallback)
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
- Бот отдаёт HTML и JSON через один тоннель (ngrok или cloudflared)
- Данные per-user: каждый видит только свои результаты поиска и подписки
- С ngrok + статическим доменом URL кнопки никогда не меняется

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
1. Запускает HTTP-сервер на порту 8742 (раздаёт `webapp/` — HTML + JSON)
2. Запускает тоннель (приоритет: ngrok → cloudflared):
   - Если в `bot_config.json` задан `ngrok_domain` → запускает `ngrok http --domain=... 8742` (URL постоянный)
   - Иначе ищет `cloudflared.exe` / `cloudflared` рядом или в PATH → quick tunnel (URL меняется при рестарте)
3. Кнопка «🌐 Открыть в приложении» появляется когда тоннель поднят

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

## Настройка ngrok (рекомендуется для постоянного URL)

1. Зарегистрируйся на [ngrok.com](https://ngrok.com) (бесплатно)
2. В дашборде: **Cloud Edge → Domains** → скопируй или создай статический домен вида `yourname.ngrok-free.app`
3. В дашборде: **Getting Started → Your Authtoken** → скопируй токен
4. На компе с ботом (Windows):
   ```
   ngrok config add-authtoken <твой_токен>
   ```
5. В `config/bot_config.json` добавь поле:
   ```json
   "ngrok_domain": "yourname.ngrok-free.app"
   ```
6. Перезапусти бот — URL кнопки Mini App теперь постоянный

**Скачать ngrok для Windows:** [ngrok.com/download](https://ngrok.com/download) → распакуй `ngrok.exe` куда-нибудь в PATH (например `C:\Windows\`)

---

## Известные баги

- **Кнопка «🛑 Остановить» при поиске** — `future.cancel()` не прерывает запущенный поток.
  Решение: заменить `run_in_executor` на subprocess с `process.terminate()`. Отложено.
- **URL тоннеля меняется при рестарте** — только при использовании cloudflared quick tunnel (fallback).
  Решение: настроить ngrok со статическим доменом (см. раздел выше).
- **JobQueue недоступен** если установлен `python-telegram-bot` без `[job-queue]` — расписание и подписки не работают.
