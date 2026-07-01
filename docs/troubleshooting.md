# Решение проблем

## Сеть и доступность

| Симптом | Причина | Решение |
|---------|---------|---------|
| zakupki.gov.ru недоступен | VPS/Mac роутит через зарубежный IP | Настроить `ZAKUPKI_PROXY` в `.env` |
| Groq API недоступен | Российский IP, US export controls | Запускать бота на зарубежном VPS |
| `409 Conflict` в логах | Два экземпляра бота одновременно | Остановить один: `systemctl stop` на VPS или `Ctrl+C` локально |
| Кнопки бота не работают | Telegram не доставляет `callback_query` | `run_polling(allowed_updates=Update.ALL_TYPES)` — уже стоит |
| TLS-ошибки через SOCKS5 | SSL-верификация не работает через SOCKS5 | `HTTPXRequest(httpx_kwargs={"verify": False})` — уже стоит |
| SSL ошибки Python 3.14 | OpenSSL 3.x повысил SECLEVEL | Патч `ctx.set_ciphers("DEFAULT@SECLEVEL=1")` в `bot.py` — уже стоит |

---

## Известные баги

| Баг | Файл | Статус |
|-----|------|--------|
| `.doc` файлы вызывают `NameError` | `agents/analyze_agent.py:73,76` — нет `import subprocess, shutil` | ❌ не исправлено |
| `data/debug_priceplan.html` создаётся при каждом первом запросе НМЦК | `parsers/priceplan.py` | нормальное поведение для отладки |
| Заказчик в НМЦК ищется через `searchString`, не отдельным параметром | ЕИС pricereq не поддерживает | ожидаемо |
| Способ закупки `pc` (Запрос котировок) игнорируется ЕИС | Баг ЕИС | убран из интерфейса |
| `okpd2_custom_code` добавляется в `searchString` | ЕИС требует числовой ID | ожидаемо |

---

## Бот / запуск

| Симптом | Причина | Решение |
|---------|---------|---------|
| Кнопки карточек `/fetch` не работают после рестарта | `context.user_data` очищается | Выполнить новый `/fetch` |
| Mini App не обновляется | Нет `github_token` в `bot_config.json` | Добавить PAT с правом `contents:write` |
| JobQueue/расписание не работает | Установлен `python-telegram-bot` без `[job-queue]` | `pip install "python-telegram-bot[job-queue]"` |
| `GROQ_API_KEY не задан` | Нет ключа в `.env` | Добавить ключ из console.groq.com |

---

## Документы закупок

| Симптом | Причина | Решение |
|---------|---------|---------|
| "Документы не найдены на ЕИС" | URL не содержит `common-info.html` | Парсер пробует fallback автоматически |
| Анализ зависает | ЕИС не отвечает или Groq долго думает | Таймаут 30 сек на список; 120 сек на Groq |
| `.doc` не читаются | `NameError: shutil/subprocess` | Исправить импорты в `analyze_agent.py` |
