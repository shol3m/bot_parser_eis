# Агентная система госзакупок

Персональный инструмент мониторинга госзакупок (44-ФЗ / 223-ФЗ).
Парсит zakupki.gov.ru, анализирует документы через Groq API, отправляет в Telegram.
**Владелец:** IT project manager, специализация — госзакупки 44-ФЗ, цифровые проекты.

---

## Архитектура

```
bot/bot.py  (Telegram UI, 3260 строк)
    │
    ├── orchestrator.py
    │       ├── agents/parser_agent.py   → parsers/zakupki.py   → zakupki.gov.ru
    │       ├── agents/priceplan_agent.py → parsers/priceplan.py → zakupki.gov.ru
    │       └── agents/analyze_agent.py  → Groq API (llama-3.3-70b-versatile)
    │
    ├── data/db.py → data/state.db (SQLite)
    └── webapp/index.html → GitHub Pages (Telegram Mini App)
```

**Иностранный VPS** — Telegram ✅ Groq ✅ / zakupki.gov.ru ❌ (нужен российский прокси)
**Российский VPS** — zakupki.gov.ru ✅ / Groq ⚠️ (возможна блокировка)

---

## Структура файлов

```
├── bot/bot.py                # точка входа
├── orchestrator.py           # координатор агентов
├── agents/                   # парсинг + анализ
├── parsers/                  # zakupki.py + priceplan.py
├── data/db.py                # SQLite схема и CRUD
├── daily_run.py              # ежедневный дайджест
├── webapp/index.html         # Telegram Mini App
├── config/                   # фильтры, промпты (не в git: bot_config.json)
├── .env                      # секреты (не в git)
└── docs/                     # документация
```

---

## Текущий статус

| | |
|--|--|
| **VPS** | не развёрнут |
| **Локально** | разработка на Mac |
| **zakupki.gov.ru** | недоступен (VPN через Aeza Stockholm) |

**Запуск локально:**
```bash
python bot/bot.py
```
Нужны `.env` и `config/bot_config.json` → см. [docs/development.md](docs/development.md)

---

## Документация

| Файл | Содержимое |
|------|-----------|
| [docs/deployment.md](docs/deployment.md) | Деплой на VPS с нуля, GitHub Actions, управление сервисом |
| [docs/development.md](docs/development.md) | Локальная разработка, текущий workflow |
| [docs/architecture.md](docs/architecture.md) | Схема модулей, callback-схема, user_data ключи, Mini App |
| [docs/config.md](docs/config.md) | bot_config.json, фильтры JSON, промпты |
| [docs/database.md](docs/database.md) | Схема SQLite, таблицы contracts + watches |
| [docs/parser.md](docs/parser.md) | Парсеры ЕИС, параметры запросов, ограничения |
| [docs/security.md](docs/security.md) | Найденные уязвимости и статус исправлений |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Известные баги и решения |

---

## Зависимости

```
python-telegram-bot[job-queue]  requests[socks]  beautifulsoup4  lxml
pdfplumber  python-docx  openpyxl  httpx[socks]  groq  python-dotenv
```

---

## Завершение рабочей сессии

Когда пользователь говорит «всё», «заканчиваем», «стоп»:
1. Обновить затронутые файлы в `docs/` и `CLAUDE.md`
2. Коммит всех изменений
3. Пуш в `origin/main`
