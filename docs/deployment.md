# Деплой на VPS

## Архитектура

**Иностранный VPS** (например Aeza Stockholm) — оптимально:
- Telegram API ✅ Groq API ✅ доступны
- zakupki.gov.ru ❌ заблокирован → нужен российский прокси (`ZAKUPKI_PROXY`)

**Российский VPS** — zakupki.gov.ru работает, но Groq API может быть заблокирован (US sanctions).

---

## Первичная установка на Ubuntu

```bash
ssh root@<VPS_IP>

# 1. Системные зависимости
apt update && apt install -y python3-pip python3-venv python3-dev \
    libxml2-dev libxslt1-dev zlib1g-dev git

# 2. Клонировать репо
cd /opt
git clone https://github.com/shol3m/bot_parser_eis.git
cd bot_parser_eis

# 3. Виртуальное окружение
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# 4. Создать .env
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=вставить_токен
GROQ_API_KEY=вставить_ключ
GITHUB_TOKEN=вставить_pat_токен
CHAT_ID=вставить_chat_id
# ZAKUPKI_PROXY=socks5://user:pass@host:1080  # если нужен российский прокси
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
# Заменить 0 на реальный chat_id

# 6. Папки данных
mkdir -p data/documents data/contracts

# 7. Systemd-сервис
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

# 8. Проверить
systemctl status bot-parser-eis
journalctl -u bot-parser-eis -n 30
```

---

## GitHub Actions автодеплой

Файл `.github/workflows/deploy.yml` уже в репо. При каждом `git push origin main` GitHub Actions автоматически деплоит на VPS.

**Нужно добавить секреты:** GitHub → репозиторий → Settings → Secrets → Actions

| Secret | Значение |
|--------|---------|
| `VPS_HOST` | IP-адрес сервера |
| `SSH_PRIVATE_KEY` | Приватный SSH-ключ для root |

**Генерация SSH-ключа (если нет):**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/vps_bot -N ""
ssh-copy-id -i ~/.ssh/vps_bot.pub root@<VPS_IP>
cat ~/.ssh/vps_bot  # скопировать в SSH_PRIVATE_KEY на GitHub
```

---

## Управление сервисом

```bash
systemctl status bot-parser-eis     # статус
journalctl -u bot-parser-eis -f     # логи в реальном времени
systemctl restart bot-parser-eis    # перезапуск
systemctl stop bot-parser-eis       # остановить
systemctl start bot-parser-eis      # запустить
```

---

## Обновление вручную

```bash
cd /opt/bot_parser_eis
git pull origin main
venv/bin/pip install -q -r requirements.txt
systemctl restart bot-parser-eis
```

---

## Полное удаление

```bash
systemctl stop bot-parser-eis
systemctl disable bot-parser-eis
rm -rf /opt/bot_parser_eis
rm /etc/systemd/system/bot-parser-eis.service
systemctl daemon-reload
```
