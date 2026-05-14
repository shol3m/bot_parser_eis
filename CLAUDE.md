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
├── docs/                     # техническая документация
├── config/
│   ├── bot_config.json       # токен, chat_id, proxy
│   ├── filters.json          # фильтры для daily_run
│   ├── saved_filters.json    # пресеты фильтров бота
│   └── prompts.json          # промпты анализа (detailed)
├── agents/
│   ├── parser_agent.py       # агент парсинга — самостоятельный, CLI + import
│   ├── analyze_agent.py      # агент анализа документов — универсальный, CLI + import
│   └── analyze_tz.py         # устарел, оставлен как бэкап
├── parsers/
│   └── zakupki.py            # низкоуровневый парсер zakupki.gov.ru
├── orchestrator.py           # координирует агентов, вызывается ботом
├── bot/
│   └── bot.py                # Telegram-бот (основной файл)
├── data/
│   ├── db.py                 # SQLite — data/state.db
│   ├── contracts/            # JSON результатов парсинга
│   └── documents/            # скачанные документы закупок
├── daily_run.py              # оркестратор: парсинг + анализ + дайджест
├── notify.py                 # утилита отправки сообщений в Telegram
└── backup_2026_05_13/        # бэкап файлов до рефакторинга агентов
```

---

## Архитектура агентов

```
bot/bot.py  (Telegram UI)
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

Каждый агент изолирован — запускается как отдельный процесс или импортируется.
`analyze_agent.py` универсален: принимает любые документы и промпт, не привязан к закупкам.

---

## Запуск

```bash
python "d:\agent_system\bot\bot.py"          # бот (держать запущенным, нужен Hiddify)
python "d:\agent_system\daily_run.py"        # ручной сбор + анализ + дайджест
python "d:\agent_system\notify.py" "текст"   # отправить сообщение в Telegram

# Агенты напрямую:
python "d:\agent_system\agents\parser_agent.py" --filters config/filters.json
python "d:\agent_system\agents\parser_agent.py" --filters '{"law":"44","date_from":"today"}'
python "d:\agent_system\agents\analyze_agent.py" doc.pdf --prompt "Проанализируй ТЗ..."
python "d:\agent_system\agents\analyze_agent.py" doc.pdf --prompt-file prompts/my.txt
```

**Важно**: всегда использовать полный абсолютный путь при запуске через Claude Code.

**Перед запуском бота**: убедиться что Hiddify подключён.
Проверка: `python -c "import httpx,asyncio; asyncio.run(httpx.AsyncClient(proxy='socks5://127.0.0.1:12334', timeout=10).get('https://api.telegram.org'))"` — должно вернуть 302.

---

## Команды бота

| Команда / Кнопка | Что делает |
|---------|-----------|
| `/start` | Регистрация, показывает главное меню |
| `/help`, `❓ Помощь` | Краткая инструкция по работе с ботом |
| `/fetch` | Поиск закупок с пагинацией — одна карточка ◀ ▶ |
| `/fetch 15.05.2026` | Закупки за конкретную дату |
| `/filters` | Настройка фильтров: ФЗ, ОКПД2, ключевые слова, сумма, дата, пресеты |
| `/watch` | Мониторинг — уведомления при появлении новых закупок |
| `/prompt` | Просмотр и редактирование промпта детального анализа |
| `/schedule` | Время ежедневного автосбора (кнопки 09:00–18:00 МСК) |
| `/status` | Статистика БД + активный пресет |
| `/restart` | Перезапуск бота (только для владельца) |
| Кнопка "🔍 Анализ" | Выбор документов с ЕИС → детальный анализ через Claude |
| Кнопка "🛑 Остановить" | Остановка поиска (⚠️ баг: не всегда срабатывает, отложено) |

---

## Автозапуск

| Что | Когда | Как |
|-----|-------|-----|
| Бот | При логине в Windows | `Startup\AgentBot.bat` → `python bot\bot.py` |
| Сбор + дайджест | По расписанию из бота | `JobQueue` внутри bot.py (МСК) |

---

## Зависимости

```
python-telegram-bot==22.x  requests  beautifulsoup4  lxml
pdfplumber  python-docx  openpyxl  httpx[socks]
```

---

## Известные баги

- **Кнопка «🛑 Остановить» при поиске** — `future.cancel()` не прерывает запущенный поток.
  Решение: заменить `run_in_executor` на subprocess с `process.terminate()`. Отложено.
