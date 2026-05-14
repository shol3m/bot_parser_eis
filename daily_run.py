"""
Дневной оркестратор: собирает закупки, делает быстрый анализ, отправляет дайджест в Telegram.
Запускается планировщиком каждое утро.
"""

import json
import re
import sys
import time
import asyncio
import subprocess
import shutil
import platform
import tempfile
import os
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent))

from parsers.zakupki import run as run_parser, fetch_contract_documents, download_document
from agents.analyze_agent import extract_text, sort_by_priority
from data.db import init_db, upsert_contract, update_quick, get_top_contracts, update_tg_message_id


def load_config(name: str) -> dict:
    with open(Path("config") / name, encoding="utf-8") as f:
        return json.load(f)


# ── Быстрый анализ ────────────────────────────────────────────────────────────

def run_claude(prompt: str) -> str:
    claude_path = shutil.which("claude.cmd") or shutil.which("claude")
    if not claude_path:
        return "ОЦЕНКА: 0/10\nКОММЕНТАРИЙ: claude CLI не найден."

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as tmp:
        tmp.write(prompt)
        tmp_path = tmp.name

    try:
        is_win = platform.system() == "Windows"
        cmd = ["cmd", "/c", claude_path, "--print", f"@{tmp_path}"] if is_win else [claude_path, "--print", f"@{tmp_path}"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=90)
        return r.stdout.strip() or r.stderr.strip() or "Нет ответа."
    except subprocess.TimeoutExpired:
        return "ОЦЕНКА: 0/10\nКОММЕНТАРИЙ: Таймаут анализа."
    except Exception as e:
        return f"ОЦЕНКА: 0/10\nКОММЕНТАРИЙ: Ошибка: {e}"
    finally:
        os.unlink(tmp_path)


def parse_quick_result(text: str) -> tuple[int, str]:
    """Извлекает оценку и комментарий из ответа быстрого анализа."""
    score = 0
    comment = text

    m = re.search(r"ОЦЕНКА:\s*(\d+)\s*/\s*10", text, re.IGNORECASE)
    if m:
        score = int(m.group(1))

    m2 = re.search(r"КОММЕНТАРИЙ:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if m2:
        comment = m2.group(1).strip()

    return score, comment


def quick_analyze(contract: dict, docs_dir: Path, prompt_template: str) -> tuple[int, str]:
    """Быстрый анализ одной закупки."""
    files = sort_by_priority(list(docs_dir.glob("*.*"))) if docs_dir.exists() else []

    # Если документов нет — анализируем только предмет и цену
    if files:
        parts = []
        total = 0
        for f in files[:3]:
            text = extract_text(f)
            if text.strip() and total < 15_000:
                parts.append(f"=== {f.name} ===\n{text[:5000]}")
                total += len(text)
        docs_text = "\n\n".join(parts) if parts else f"Документы недоступны. Предмет: {contract.get('subject','')}. НМЦ: {contract.get('price','')}."
    else:
        docs_text = f"Документы не скачаны.\nПредмет закупки: {contract.get('subject','не указан')}\nНМЦ: {contract.get('price','не указана')}\nЗаказчик: {contract.get('customer','не указан')}"

    prompt = prompt_template.replace("{documents_text}", docs_text)
    result = run_claude(prompt)
    return parse_quick_result(result)


# ── Telegram отправка ──────────────────────────────────────────────────────────

async def send_digest(top_contracts: list[dict], bot_cfg: dict) -> None:
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

    bot = Bot(token=bot_cfg["token"])
    chat_id = bot_cfg["chat_id"]

    if not top_contracts:
        await bot.send_message(chat_id=chat_id, text="Сегодня закупок по критериям не найдено.")
        return

    header = f"📋 *Дайджест закупок на сегодня*\nТоп-{len(top_contracts)} по разделу J (ИТ/связь)\n\n"
    await bot.send_message(chat_id=chat_id, text=header, parse_mode="Markdown")

    for c in top_contracts:
        score = c["quick_score"]
        stars = "⭐" * min(score, 5) + ("🔥" if score >= 8 else "")
        price = c.get("price") or "н/д"
        subject = (c.get("subject") or "Предмет не указан")[:120]
        customer = (c.get("customer") or "")[:60]
        comment = (c.get("quick_comment") or "")[:300]

        text = (
            f"{stars} *{score}/10* — {subject}\n"
            f"💰 {price}\n"
            f"🏛 {customer}\n"
            f"_{comment}_"
        )

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔍 Детальный анализ", callback_data=f"detail:{c['id']}"),
            InlineKeyboardButton("🔗 Открыть", url=c.get("url", "https://zakupki.gov.ru")),
        ]])

        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        update_tg_message_id(c["id"], msg.message_id)
        await asyncio.sleep(0.4)  # не флудим


# ── Главная функция ────────────────────────────────────────────────────────────

def main():
    print("=== Дневной запуск ===")
    init_db()

    prompts_cfg = load_config("prompts.json")
    bot_cfg = load_config("bot_config.json")
    quick_prompt = prompts_cfg["quick"]
    min_score = prompts_cfg.get("min_score", 6)
    top_n = prompts_cfg.get("top_n", 10)

    # 1. Собираем все закупки за день
    print("\n[1/4] Сбор закупок...")
    config_path = str(Path(__file__).parent / "config" / "filters.json")
    contracts = run_parser(config_path=config_path, max_pages=0)  # все страницы
    print(f"Собрано: {len(contracts)} закупок")

    # 2. Скачиваем документы + быстрый анализ
    print(f"\n[2/4] Скачивание документов и быстрый анализ...")
    docs_root = Path(__file__).parent / "data" / "documents"
    docs_root.mkdir(exist_ok=True)

    for i, c in enumerate(contracts):
        number = c.get("number", f"contract_{i}")
        safe_num = number.replace("/", "_").replace(" ", "")
        contract_dir = docs_root / safe_num
        contract_dir.mkdir(exist_ok=True)

        # Сохраняем в БД
        contract_id = upsert_contract({
            "number": number,
            "subject": c.get("subject", ""),
            "price": c.get("price", ""),
            "customer": c.get("customer", ""),
            "url": c.get("url", ""),
        })

        # Скачиваем документы если папка пустая
        if not any(contract_dir.iterdir()):
            url = c.get("url", "")
            if url:
                docs = fetch_contract_documents(url)
                for doc in docs[:4]:
                    try:
                        download_document(doc, contract_dir)
                    except Exception as e:
                        print(f"    Ошибка скачивания {doc.get('name','?')}: {e}")
                time.sleep(0.5)

        # Быстрый анализ
        print(f"  [{i+1}/{len(contracts)}] {number}...", end=" ", flush=True)
        score, comment = quick_analyze(c, contract_dir, quick_prompt)
        update_quick(contract_id, score, comment, str(contract_dir))
        print(f"{score}/10")

        time.sleep(0.3)

    # 3. Выбираем топ
    print(f"\n[3/4] Выбор топ-{top_n} с оценкой >= {min_score}...")
    top = get_top_contracts(min_score, top_n)
    print(f"Подходящих закупок: {len(top)}")

    # 4. Отправляем в Telegram
    if bot_cfg.get("token") and bot_cfg["token"] != "ВСТАВЬ_ТОКЕН_СЮДА":
        print(f"\n[4/4] Отправка в Telegram...")
        asyncio.run(send_digest(top, bot_cfg))
        print("Отправлено.")
    else:
        print("\n[4/4] Telegram не настроен — пропускаем отправку.")
        print("Топ закупок (без Telegram):")
        for c in top:
            print(f"  {c['quick_score']}/10 | {c.get('subject','')[:60]} | {c.get('price','')}")


if __name__ == "__main__":
    main()
