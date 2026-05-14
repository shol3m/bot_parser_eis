"""
Утилита для отправки сообщений в Telegram от имени бота.
Использование: python notify.py "текст сообщения"
"""

import sys
import json
import httpx
from pathlib import Path

CFG_PATH = Path(__file__).parent / "config" / "bot_config.json"


def send(text: str) -> bool:
    if not CFG_PATH.exists():
        print(f"Конфиг не найден: {CFG_PATH}", file=sys.stderr)
        return False
    try:
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Ошибка чтения конфига: {e}", file=sys.stderr)
        return False
    token   = cfg.get("token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id:
        print("Конфиг не содержит token или chat_id", file=sys.stderr)
        return False
    proxy   = cfg.get("proxy") or None

    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

    try:
        client_kwargs = {"proxy": proxy, "verify": False} if proxy else {"trust_env": False}
        with httpx.Client(**client_kwargs, timeout=15) as client:
            r = client.post(url, json=payload)
            return r.status_code == 200
    except Exception as e:
        print(f"Ошибка отправки: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python notify.py 'текст'")
        sys.exit(1)
    msg = " ".join(sys.argv[1:])
    ok  = send(msg)
    sys.exit(0 if ok else 1)
