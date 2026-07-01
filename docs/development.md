# Локальная разработка

## Текущий статус

| Место | Статус |
|-------|--------|
| VPS (Aeza Stockholm) | ❌ не развёрнут |
| Локально (Mac) | ✅ рабочий режим разработки |

---

## Первый запуск на Mac

```bash
cd /Users/daniil/Desktop/bot_parser_eis

# 1. Создать .env
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=  # из BotFather
GROQ_API_KEY=        # из console.groq.com
GITHUB_TOKEN=        # из GitHub Settings → Tokens (scope: contents:write)
CHAT_ID=             # свой Telegram chat_id
EOF

# 2. Создать config/bot_config.json
cat > config/bot_config.json << 'EOF'
{
  "token": "",
  "chat_id": 0,
  "allowed_users": [],
  "proxy": null,
  "github_token": ""
}
EOF

# 3. Установить зависимости (если не установлены)
pip install -r requirements.txt

# 4. Запустить
python bot/bot.py
```

---

## Что работает локально

| Функция | Статус | Причина |
|---------|--------|---------|
| Telegram (команды, кнопки) | ✅ | Telegram API доступен через VPN |
| Groq API (анализ документов) | ✅ | Groq доступен с Aeza Stockholm IP |
| Mini App (GitHub Pages) | ✅ | GitHub API работает |
| Поиск закупок (zakupki.gov.ru) | ❌ | VPN (Aeza Stockholm) заблокирован ЕИС |
| Поиск НМЦК (zakupki.gov.ru) | ❌ | То же |

> Mac всегда работает через VPN Aeza Stockholm → zakupki.gov.ru недоступен.
> Для парсинга нужен российский прокси (`ZAKUPKI_PROXY`). До его настройки — разрабатывать остальное.

---

## Рабочий workflow

```bash
# Разрабатываешь локально
python bot/bot.py

# Коммит и пуш
git add -p
git commit -m "..."
git push origin main
# GitHub Actions задеплоит на VPS когда он будет поднят
```

---

## Когда поднимать VPS снова

1. Настроить российский прокси для zakupki.gov.ru (см. [deployment.md](deployment.md))
2. Занести `ZAKUPKI_PROXY` в `.env` на VPS
3. Развернуть по инструкции в deployment.md
4. Остановить локальный бот (два экземпляра конфликтуют — `409 Conflict`)
