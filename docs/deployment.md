# Деплой и автозапуск

---

## Текущая среда

- **ОС**: Windows 10 Pro
- **Python**: `C:\Users\Даниил\AppData\Local\Python\bin\python.exe` (3.14)
- **Рабочая папка**: `D:\agent_system`
- **Прокси**: Hiddify, порт 12334 (SOCKS5)

---

## Автозапуск при входе в Windows

Файл: `C:\Users\Даниил\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\AgentBot.bat`

```bat
@echo off
cd /d D:\agent_system
"C:\Users\Даниил\AppData\Local\Python\bin\python.exe" bot\bot.py
```

Бот запускается автоматически при логине. Окно терминала остаётся открытым (нормальное поведение для `.bat`).

---

## Ручной запуск

```bash
# В терминале из D:\agent_system
python bot\bot.py
```

---

## Перезапуск

**Через Telegram (рекомендуется):**
```
/restart
```
Бот штатно останавливает polling, закрывает соединения, затем перезапускается через `os.execv`. Один процесс, без 409 Conflict.

**Через терминал:**
```
Ctrl+C  →  стрелка вверх  →  Enter
```

**Принудительно (если завис):**
```bat
taskkill /F /IM python.exe /T
```
Затем запустить бота заново.

---

## Проверка работоспособности

```bash
# Hiddify подключён?
python -c "import httpx,asyncio; asyncio.run(httpx.AsyncClient(proxy='socks5://127.0.0.1:12334', timeout=10).get('https://api.telegram.org'))"
# Ожидаем: 302

# Бот запущен?
tasklist /FI "IMAGENAME eq python.exe"

# Последние события бота:
# Смотреть bot_debug.log (последние строки)
```

---

## Переезд на VPS (план)

При деплое на сервер нужно:

1. Заменить `run_claude()` в `bot.py` на вызов **Anthropic API** напрямую (убрать зависимость от Claude CLI)
2. Убрать зависимость от Hiddify — на сервере Telegram доступен напрямую, убрать прокси из `bot_config.json`
3. Настроить `systemd` или `supervisor` вместо Windows Startup
4. Мигрировать на мультипользовательскую БД (добавить `user_id` к фильтрам, пресетам, вотчам)
5. Рассмотреть Telegram Mini App как интерфейс (требует HTTPS)
