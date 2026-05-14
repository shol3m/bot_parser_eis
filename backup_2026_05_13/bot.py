"""
Telegram-бот агентной системы госзакупок.
/start    — регистрация
/filters  — настройка фильтров и пресетов
/fetch    — поиск закупок с пагинацией
/schedule — время ежедневного автосбора
/status   — статистика БД
"""

import logging
logging.basicConfig(
    filename="bot_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)
import ssl as _ssl

# Python 3.14 + OpenSSL 3.x: снижаем SECLEVEL до 1 чтобы не ломался TLS через прокси
_orig_ctx = _ssl._create_default_https_context
def _patched_ctx(*a, **kw):
    ctx = _orig_ctx(*a, **kw)
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except Exception:
        pass
    return ctx
_ssl._create_default_https_context = _patched_ctx

import json
import sys
import asyncio
import subprocess
import shutil
import platform
import tempfile
import os
import datetime
import threading
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters as tg_filters,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError
from telegram.request import HTTPXRequest

from data.db import (
    init_db, get_contract, update_detail, upsert_contract,
    add_watch, list_watches, get_watch, delete_watch,
    touch_watch, get_all_active_watches,
)
from agents.analyze_tz import extract_text, sort_by_priority


# ── Пути к конфигам ────────────────────────────────────────────────────────────

CONFIG_DIR    = Path(__file__).parent.parent / "config"
BOT_CFG_PATH  = CONFIG_DIR / "bot_config.json"
PRESETS_PATH  = CONFIG_DIR / "saved_filters.json"
PROMPTS_PATH  = CONFIG_DIR / "prompts.json"

# UTC+3 (Москва) для планировщика
MSK = datetime.timezone(datetime.timedelta(hours=3))

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🔍 Поиск", "⚙️ Фильтры"],
        ["👁 Мониторинг", "📝 Промпт"],
        ["⏰ Расписание", "📊 Статус"],
        ["❓ Помощь"],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите раздел…",
)

HELP_TEXT = (
    "📖 *Инструкция по работе с ботом*\n\n"
    "*Типичный сценарий:*\n"
    "1\\. ⚙️ *Фильтры* — настройте ФЗ, ОКПД2, ключевые слова, сумму и дату\n"
    "2\\. 💾 Сохраните пресет чтобы не вводить фильтры заново\n"
    "3\\. 🔍 *Поиск* — запускает парсинг zakupki\\.gov\\.ru \\(1–2 мин\\)\n"
    "4\\. ◀ ▶ Листайте карточки закупок\n"
    "5\\. 🔍 *Анализ* — выбираете документы с ЕИС → Claude читает ТЗ и даёт оценку\n\n"
    "*Автоматизация:*\n"
    "• 👁 *Мониторинг* —  проверяка новых закупок по расписанию \\(1–24 ч\\) и присылает уведомления\n"
    "• ⏰ *Расписание* — ежедневный сбор \\+ дайджест в выбранное время МСК\n\n"
    "*Полезно знать:*\n"
    "• `/fetch 15.05.2026` — поиск за конкретную дату\n"
    "• 📝 *Промпт* — изменить инструкцию для детального анализа ТЗ\n"
    "• 📊 *Статус* — статистика БД и активный пресет\n"
    "• ⏭ *Пропустить* — убирает закупку из текущей сессии"
)

DEFAULT_FILTER: dict = {
    "keywords":      [],
    "okpd2_key":     8873870,
    "okpd2_section": "J",
    "region_codes":  [],
    "price_from":    None,
    "price_to":      None,
    "law":           "44",
    "date_from":     "today",
    "date_to":       "today",
}


# ── Конфиги ────────────────────────────────────────────────────────────────────

def load_bot_cfg() -> dict:
    if not BOT_CFG_PATH.exists():
        print(f"ОШИБКА: файл конфига не найден: {BOT_CFG_PATH}")
        sys.exit(1)
    with open(BOT_CFG_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"ОШИБКА: повреждён {BOT_CFG_PATH}: {e}")
            sys.exit(1)

def save_bot_cfg(cfg: dict) -> None:
    with open(BOT_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def load_prompts() -> dict:
    with open(PROMPTS_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── Пресеты ────────────────────────────────────────────────────────────────────

def load_presets() -> dict:
    if not PRESETS_PATH.exists():
        data = {"active": "default", "presets": {"default": deepcopy(DEFAULT_FILTER)}}
        _save_presets(data)
        return data
    with open(PRESETS_PATH, encoding="utf-8") as f:
        return json.load(f)

def _save_presets(data: dict) -> None:
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_active_filter() -> dict:
    data = load_presets()
    name = data.get("active", "default")
    return deepcopy(data["presets"].get(name, DEFAULT_FILTER))


# ── Отображение фильтра ────────────────────────────────────────────────────────

def _filter_summary(f: dict) -> str:
    law  = f.get("law", "44")
    okpd = f.get("okpd2_section") or "Все"
    pf   = f.get("price_from")
    pt   = f.get("price_to")
    df   = f.get("date_from", "today")
    dt_  = f.get("date_to",   "today")
    kw   = f.get("keywords") or []

    if pf or pt:
        s_pf = f"{int(pf):,}".replace(",", " ") + " ₽" if pf else "0"
        s_pt = f"{int(pt):,}".replace(",", " ") + " ₽" if pt else "∞"
        price_str = f"{s_pf} — {s_pt}"
    else:
        price_str = "любая"

    date_str = df if df == dt_ else f"{df} — {dt_}"
    kw_str   = ", ".join(kw) if kw else "не заданы"
    return (
        f"ФЗ: {law} | ОКПД2: {okpd}\n"
        f"Сумма: {price_str}\n"
        f"Дата: {date_str}\n"
        f"Слова: {kw_str}"
    )


def _filter_menu_text(draft: dict, active_name: str, note: str = "") -> str:
    text = (
        f"⚙️ *Настройка фильтров*\n"
        f"Активный пресет: *{active_name}*\n\n"
        f"{_filter_summary(draft)}"
    )
    if note:
        text += f"\n\n✅ {note}"
    return text


def _filter_keyboard(draft: dict, presets: dict) -> InlineKeyboardMarkup:
    law  = draft.get("law", "44")
    okpd = draft.get("okpd2_section") or "all"
    pf   = draft.get("price_from")
    pt   = draft.get("price_to")

    def _mark(cond):
        return "✅ " if cond else ""

    pf_lbl = f"От: {int(pf):,} ₽".replace(",", " ") if pf else "Сумма от: любая"
    pt_lbl = f"До: {int(pt):,} ₽".replace(",", " ") if pt else "Сумма до: любая"

    kw      = draft.get("keywords") or []
    kw_lbl  = f"🔤 Слова: {', '.join(kw[:3])}{'…' if len(kw) > 3 else ''}" if kw else "🔤 Ключевые слова…"

    rows = [
        # Закон
        [
            InlineKeyboardButton(f"{_mark(law == '44')}44-ФЗ",    callback_data="f:law:44"),
            InlineKeyboardButton(f"{_mark(law == '223')}223-ФЗ",   callback_data="f:law:223"),
            InlineKeyboardButton(f"{_mark(law == 'both')}Оба ФЗ",  callback_data="f:law:both"),
        ],
        # ОКПД2
        [
            InlineKeyboardButton(f"{_mark(okpd == 'J')}Раздел J (ИТ)", callback_data="f:okpd:J"),
            InlineKeyboardButton(f"{_mark(okpd == 'all')}Все разделы",  callback_data="f:okpd:all"),
            InlineKeyboardButton("Свой код...",                          callback_data="f:okpd:custom"),
        ],
        # Ключевые слова
        [
            InlineKeyboardButton(kw_lbl,        callback_data="f:kw:set"),
            InlineKeyboardButton("✖ Очистить",  callback_data="f:kw:clear"),
        ],
        # Сумма
        [
            InlineKeyboardButton(pf_lbl, callback_data="f:price_from"),
            InlineKeyboardButton(pt_lbl, callback_data="f:price_to"),
        ],
        # Дата
        [
            InlineKeyboardButton("📅 Сегодня",  callback_data="f:date:today"),
            InlineKeyboardButton("📅 Вчера",    callback_data="f:date:yesterday"),
            InlineKeyboardButton("📅 Период…",  callback_data="f:date:custom"),
        ],
        # Пресеты
        [
            InlineKeyboardButton("💾 Сохранить пресет",             callback_data="f:save"),
            InlineKeyboardButton(f"📋 Пресеты ({len(presets)})",    callback_data="f:presets"),
        ],
        # Применить
        [
            InlineKeyboardButton("🔍 Искать с этими фильтрами", callback_data="f:apply"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


async def _refresh_filter_msg(query, context, note: str = "") -> None:
    """Обновляет уже отправленное меню фильтров."""
    data = load_presets()
    draft = context.user_data.get("draft", DEFAULT_FILTER)
    active_name = data.get("active", "default")
    text = _filter_menu_text(draft, active_name, note)
    kb   = _filter_keyboard(draft, data["presets"])
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except (BadRequest, TimedOut, NetworkError):
        pass


# ── Claude / анализ ────────────────────────────────────────────────────────────

def run_claude(prompt: str) -> str:
    claude_path = shutil.which("claude.cmd") or shutil.which("claude")
    if not claude_path:
        return "claude CLI не найден."
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as tmp:
        tmp.write(prompt)
        tmp_path = tmp.name
    try:
        is_win = platform.system() == "Windows"
        cmd = ["cmd", "/c", claude_path, "--print", f"@{tmp_path}"] if is_win \
              else [claude_path, "--print", f"@{tmp_path}"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
        return r.stdout.strip() or r.stderr.strip() or "Нет ответа."
    except subprocess.TimeoutExpired:
        return "Таймаут (120 сек)."
    except Exception as e:
        return f"Ошибка: {e}"
    finally:
        os.unlink(tmp_path)


def detailed_analysis(contract: dict, prompt_template: str) -> str:
    docs_dir = Path(contract.get("docs_dir", ""))
    files = sort_by_priority(list(docs_dir.glob("*.*"))) if docs_dir.exists() else []
    if files:
        parts, total = [], 0
        for f in files:
            text = extract_text(f)
            if text.strip() and total < 40_000:
                parts.append(f"=== {f.name} ===\n{text}")
                total += len(text)
        docs_text = "\n\n".join(parts) if parts else "Документы недоступны."
    else:
        docs_text = (
            f"Документы не найдены.\n"
            f"Предмет: {contract.get('subject','')}\n"
            f"НМЦ: {contract.get('price','')}\n"
            f"Заказчик: {contract.get('customer','')}"
        )
    return run_claude(prompt_template.replace("{documents_text}", docs_text))


# ── Парсер ─────────────────────────────────────────────────────────────────────

def _fetch_with_filters(filters: dict, stop_event=None) -> list[dict]:
    """Запускает парсер. law=both — два запроса, результаты объединяются."""
    from parsers.zakupki import run as run_parser

    def _run_single(law_val: str) -> list[dict]:
        f = dict(filters, law=law_val)
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir="config", prefix="_fetch_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(f, fp, ensure_ascii=False)
            results = run_parser(config_path=tmp_path, max_pages=0, stop_event=stop_event)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        for r in results:
            r["_law"] = law_val
        return results

    law = filters.get("law", "44")
    if law == "both":
        combined, seen = [], set()
        for r in _run_single("44"):
            key = r.get("number") or r.get("url", "")
            if key not in seen:
                seen.add(key)
                combined.append(r)
        if not (stop_event and stop_event.is_set()):
            for r in _run_single("223"):
                key = r.get("number") or r.get("url", "")
                if key not in seen:
                    seen.add(key)
                    combined.append(r)
        return combined
    return _run_single(law)


def _save_to_db(contracts: list[dict]) -> list[dict]:
    for c in contracts:
        db_id = upsert_contract({
            "number":   c.get("number",   ""),
            "subject":  c.get("subject",  ""),
            "price":    c.get("price",    ""),
            "customer": c.get("customer", ""),
            "url":      c.get("url",      ""),
        })
        c["_db_id"] = db_id
    return contracts


# ── Пагинация ──────────────────────────────────────────────────────────────────

def _card_text(contracts: list[dict], idx: int) -> str:
    c      = contracts[idx]
    score  = c.get("quick_score") or 0
    stars  = "⭐" * min(score, 5) + ("🔥" if score >= 8 else "")
    s_line = f"{stars} *{score}/10*  " if score else ""

    subj     = " ".join((c.get("subject") or "Предмет не указан").split())[:150]
    price    = (c.get("price") or "н/д").strip()
    customer = (c.get("customer") or "").strip()[:80]
    comment  = (c.get("quick_comment") or "").strip()[:200]
    law_tag  = c.get("_law", "")
    law_str  = f"  _{law_tag}-ФЗ_" if law_tag else ""
    date_pub = c.get("date_updated", "").strip()
    date_end = c.get("date_end", "").strip()

    lines = [f"{s_line}*{subj}*", f"💰 {price}{law_str}"]
    if customer:
        lines.append(f"🏛 {customer}")
    if date_pub or date_end:
        date_line = ""
        if date_pub:
            date_line += f"📅 Обновлено: {date_pub}"
        if date_end:
            date_line += f"  ⏳ До: {date_end}"
        lines.append(date_line)
    if comment:
        lines.append(f"\n_{comment}_")
    lines.append(f"\n📊 {idx + 1} / {len(contracts)}")
    return "\n".join(lines)


def _card_keyboard(contracts: list[dict], idx: int) -> InlineKeyboardMarkup:
    c      = contracts[idx]
    db_id  = c.get("_db_id")
    url    = c.get("url", "https://zakupki.gov.ru")

    nav_row = []
    if idx > 0:
        nav_row.append(InlineKeyboardButton("◀", callback_data="pg:prev"))
    nav_row.append(InlineKeyboardButton("⏭ Пропустить", callback_data="pg:skip"))
    if idx < len(contracts) - 1:
        nav_row.append(InlineKeyboardButton("▶", callback_data="pg:next"))

    action_row = []
    if db_id:
        action_row.append(InlineKeyboardButton("🔍 Анализ", callback_data=f"detail:{db_id}"))
    action_row.append(InlineKeyboardButton("🔗 Открыть", url=url))

    return InlineKeyboardMarkup([nav_row, action_row])


# ── Хэндлеры: start / status ───────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    cfg = load_bot_cfg()
    if cfg.get("chat_id") != chat_id:
        cfg["chat_id"] = chat_id
        save_bot_cfg(cfg)

    await update.message.reply_text(
        "👋 *Агентная система госзакупок*\n\n"
        "🔍 *Поиск* — найти закупки по текущим фильтрам\n"
        "⚙️ *Фильтры* — ФЗ, ОКПД2, ключевые слова, сумма, дата, пресеты\n"
        "👁 *Мониторинг* — авто-уведомления при появлении новых закупок\n"
        "📝 *Промпт* — инструкция для детального анализа ТЗ\n"
        "⏰ *Расписание* — ежедневный сбор и дайджест\n"
        "📊 *Статус* — статистика базы данных",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📖 Инструкция", callback_data="help:show"),
        ]]),
    )
    await update.message.reply_text("Выберите раздел:", reply_markup=MAIN_MENU)


async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = load_bot_cfg()
    if update.effective_chat.id != cfg.get("chat_id"):
        return
    await update.message.reply_text("♻️ Перезапускаю...")
    context.application.stop_running()  # штатная остановка polling — рестарт произойдёт в main()


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from data.db import get_conn
    with get_conn() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
        today    = conn.execute("SELECT COUNT(*) FROM contracts WHERE date_found=date('now')").fetchone()[0]
        analyzed = conn.execute("SELECT COUNT(*) FROM contracts WHERE detail_text IS NOT NULL").fetchone()[0]

    docs_count = (
        sum(1 for d in Path("data/documents").iterdir() if d.is_dir())
        if Path("data/documents").exists() else 0
    )
    data         = load_presets()
    active_name  = data.get("active", "default")
    active_flt   = data["presets"].get(active_name, {})
    cfg          = load_bot_cfg()
    sched        = cfg.get("schedule_time", "не задано")

    await update.message.reply_text(
        f"📊 *Состояние системы*\n\n"
        f"Закупок в БД: {total}\n"
        f"Собрано сегодня: {today}\n"
        f"Детально проанализировано: {analyzed}\n"
        f"Папок с документами: {docs_count}\n\n"
        f"Активный пресет: *{active_name}*\n"
        f"{_filter_summary(active_flt)}\n\n"
        f"⏰ Автосбор: {sched} МСК",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def callback_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _qanswer(query)
    await query.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN_V2)


# ── Хэндлеры: /filters ────────────────────────────────────────────────────────

async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data        = load_presets()
    active_name = data.get("active", "default")

    if "draft" not in context.user_data:
        context.user_data["draft"] = deepcopy(data["presets"].get(active_name, DEFAULT_FILTER))

    draft = context.user_data["draft"]
    text  = _filter_menu_text(draft, active_name)
    kb    = _filter_keyboard(draft, data["presets"])
    msg   = await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    context.user_data["filter_msg_id"] = msg.message_id


async def _qanswer(query, text: str = "") -> None:
    """query.answer() с текстом — мгновенный тост. Не падает при таймауте."""
    try:
        await query.answer(text=text, show_alert=False)
    except (TimedOut, NetworkError, Exception):
        pass


async def callback_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    # Инициализируем черновик если нет
    if "draft" not in context.user_data:
        data        = load_presets()
        active_name = data.get("active", "default")
        context.user_data["draft"] = deepcopy(data["presets"].get(active_name, DEFAULT_FILTER))

    draft = context.user_data["draft"]
    parts = query.data.split(":", 2)  # ["f", "sub", "val?"]
    sub   = parts[1]

    if sub == "kw":
        val = parts[2]
        if val == "set":
            await _qanswer(query, "Введите слова ↓")
            context.user_data["await_input"]   = "keywords"
            context.user_data["filter_msg_id"] = query.message.message_id
            await query.message.reply_text(
                "Введите ключевые слова через запятую:\n"
                "Например: `разработка ПО, информационная система`\n\n"
                "Отправьте `-` чтобы очистить.",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif val == "clear":
            draft["keywords"] = []
            await _qanswer(query, "✅ Слова очищены")
            await _refresh_filter_msg(query, context)

    elif sub == "law":
        val = parts[2]
        draft["law"] = val
        label = {"44": "44-ФЗ", "223": "223-ФЗ", "both": "Оба ФЗ"}.get(val, val)
        await _qanswer(query, f"✅ {label}")
        await _refresh_filter_msg(query, context)

    elif sub == "okpd":
        val = parts[2]
        if val == "J":
            draft["okpd2_section"] = "J"
            draft["okpd2_key"]     = 8873870
            await _qanswer(query, "✅ Раздел J (ИТ)")
            await _refresh_filter_msg(query, context)
        elif val == "all":
            draft["okpd2_section"] = None
            draft["okpd2_key"]     = None
            await _qanswer(query, "✅ Все разделы")
            await _refresh_filter_msg(query, context)
        elif val == "custom":
            await _qanswer(query, "Введите код ↓")
            context.user_data["await_input"]   = "okpd2_code"
            context.user_data["filter_msg_id"] = query.message.message_id
            await query.message.reply_text(
                "Введите код ОКПД2, например `72.19.1`.\n"
                "⚠️ Поиск по коду работает только если он совпадает с разделом ЕИС.",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif sub == "price_from":
        await _qanswer(query, "Введите сумму ↓")
        context.user_data["await_input"]   = "price_from"
        context.user_data["filter_msg_id"] = query.message.message_id
        await query.message.reply_text(
            "Введите минимальную сумму в рублях (например `500000`).\n"
            "Отправьте `0` чтобы убрать фильтр:",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif sub == "price_to":
        await _qanswer(query, "Введите сумму ↓")
        context.user_data["await_input"]   = "price_to"
        context.user_data["filter_msg_id"] = query.message.message_id
        await query.message.reply_text(
            "Введите максимальную сумму в рублях (например `5000000`).\n"
            "Отправьте `0` чтобы убрать фильтр:",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif sub == "date":
        val = parts[2]
        if val == "today":
            draft["date_from"] = draft["date_to"] = "today"
            await _qanswer(query, "✅ Сегодня")
            await _refresh_filter_msg(query, context)
        elif val == "yesterday":
            draft["date_from"] = draft["date_to"] = "yesterday"
            await _qanswer(query, "✅ Вчера")
            await _refresh_filter_msg(query, context)
        elif val == "custom":
            await _qanswer(query, "Введите период ↓")
            context.user_data["await_input"]   = "date_from"
            context.user_data["filter_msg_id"] = query.message.message_id
            await query.message.reply_text(
                "Введите дату ОТ в формате `ДД.ММ.ГГГГ`:",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif sub == "save":
        await _qanswer(query, "Введите название ↓")
        context.user_data["await_input"]   = "preset_name"
        context.user_data["filter_msg_id"] = query.message.message_id
        await query.message.reply_text("Введите название пресета:")

    elif sub == "presets":
        await _qanswer(query)
        await _show_presets_menu(query, context)

    elif sub == "apply":
        context.user_data["pending_filter"] = deepcopy(draft)
        await _qanswer(query, "✅ Фильтры применены")
        await query.message.reply_text("✅ Фильтры готовы. Запустите /fetch для поиска.")


async def _show_presets_menu(query, context) -> None:
    data    = load_presets()
    presets = data["presets"]
    active  = data.get("active", "default")

    if not presets:
        await query.message.reply_text("Нет сохранённых пресетов.")
        return

    rows = []
    for name in presets:
        mark = "✅ " if name == active else ""
        rows.append([
            InlineKeyboardButton(f"{mark}{name}", callback_data=f"ps:load:{name}"),
            InlineKeyboardButton("🗑",             callback_data=f"ps:del:{name}"),
        ])
    rows.append([InlineKeyboardButton("← Назад", callback_data="ps:back")])

    try:
        await query.edit_message_text(
            "📋 *Сохранённые пресеты*\nНажмите имя чтобы загрузить:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except (BadRequest, TimedOut, NetworkError):
        await query.message.reply_text(
            "📋 *Сохранённые пресеты*\nНажмите имя чтобы загрузить:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows),
        )


async def callback_preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except (TimedOut, NetworkError):
        pass
    parts = query.data.split(":", 2)  # ["ps", "sub", "name"]
    sub   = parts[1]
    data  = load_presets()

    if sub == "load" and len(parts) == 3:
        name = parts[2]
        if name in data["presets"]:
            data["active"] = name
            _save_presets(data)
            context.user_data["draft"] = deepcopy(data["presets"][name])
            context.user_data.pop("pending_filter", None)
            await _refresh_filter_msg(query, context, note=f"Пресет «{name}» загружен")

    elif sub == "del" and len(parts) == 3:
        name = parts[2]
        if name == "default":
            await query.answer("Нельзя удалить пресет «default»", show_alert=True)
            return
        if name in data["presets"]:
            del data["presets"][name]
            if data.get("active") == name:
                data["active"] = "default"
            _save_presets(data)
        await _show_presets_menu(query, context)

    elif sub == "back":
        await _refresh_filter_msg(query, context)


# ── Хэндлер: текстовый ввод параметров ────────────────────────────────────────

MENU_COMMANDS: dict = {}  # заполняется после объявления всех функций


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()

    # Кнопки главного меню
    if text in MENU_COMMANDS and not context.user_data.get("await_input"):
        await MENU_COMMANDS[text](update, context)
        return

    awaiting = context.user_data.get("await_input")
    if not awaiting:
        return
    draft = context.user_data.setdefault("draft", deepcopy(DEFAULT_FILTER))

    async def _ask_again(msg: str) -> None:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _done(note: str) -> None:
        context.user_data.pop("await_input", None)
        await update.message.reply_text(f"✅ {note}")
        await _try_refresh_filter_menu(update, context)

    if awaiting == "keywords":
        if text == "-":
            draft["keywords"] = []
            await _done("Ключевые слова очищены")
        else:
            kw = [w.strip() for w in text.split(",") if w.strip()]
            draft["keywords"] = kw
            await _done(f"Слова: {', '.join(kw)}")

    elif awaiting in ("price_from", "price_to"):
        try:
            val = float(text.replace(" ", "").replace(",", "."))
            draft[awaiting] = val if val > 0 else None
            label = f"{int(val):,} ₽".replace(",", " ") if val > 0 else "убрана"
            await _done(f"{'Сумма от' if awaiting == 'price_from' else 'Сумма до'}: {label}")
        except ValueError:
            await _ask_again("Не понял. Введите число, например `500000`.")

    elif awaiting == "date_from":
        if _is_valid_date(text):
            draft["date_from"] = text
            context.user_data["await_input"] = "date_to"
            await update.message.reply_text(
                f"✅ Дата от: {text}\nТеперь введите дату ДО (или ту же дату):",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await _ask_again("Неверный формат. Используйте `ДД.ММ.ГГГГ`, например `01.05.2026`.")

    elif awaiting == "date_to":
        if _is_valid_date(text):
            draft["date_to"] = text
            await _done(f"Период: {draft.get('date_from')} — {text}")
        else:
            await _ask_again("Неверный формат. Используйте `ДД.ММ.ГГГГ`.")

    elif awaiting == "okpd2_code":
        draft["okpd2_section"] = text
        draft["okpd2_key"]     = None
        await _done(f"ОКПД2: {text}")

    elif awaiting == "prompt_detailed":
        context.user_data.pop("await_input", None)
        if text == "-":
            new_prompt = DEFAULT_DETAILED_PROMPT
            label = "Промпт сброшен к дефолту"
        else:
            new_prompt = text
            if "{documents_text}" not in new_prompt:
                new_prompt += "\n\n---\n\nДОКУМЕНТЫ ЗАКУПКИ:\n{documents_text}"
            label = "Промпт сохранён"
        prompts = load_prompts()
        prompts["detailed"] = new_prompt
        with open(PROMPTS_PATH, "w", encoding="utf-8") as f:
            json.dump(prompts, f, ensure_ascii=False, indent=2)
        await update.message.reply_text(f"✅ {label}")

    elif awaiting == "preset_name":
        name = text.strip()
        if not name:
            await _ask_again("Имя не может быть пустым.")
            return
        pdata = load_presets()
        pdata["presets"][name] = deepcopy(draft)
        pdata["active"]        = name
        _save_presets(pdata)
        context.user_data.pop("await_input", None)
        await update.message.reply_text(f"✅ Пресет «{name}» сохранён и активирован.")
        await _try_refresh_filter_menu(update, context)


async def handle_document_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("await_input") != "prompt_detailed":
        return

    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("Поддерживаются только .txt файлы.")
        return

    if doc.file_size > 50_000:
        await update.message.reply_text("Файл слишком большой (максимум 50 КБ).")
        return

    file = await context.bot.get_file(doc.file_id)
    content = await file.download_as_bytearray()
    text = content.decode("utf-8", errors="replace").strip()

    context.user_data.pop("await_input", None)
    if "{documents_text}" not in text:
        text += "\n\n---\n\nДОКУМЕНТЫ ЗАКУПКИ:\n{documents_text}"

    prompts = load_prompts()
    prompts["detailed"] = text
    with open(PROMPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)
    await update.message.reply_text(f"✅ Промпт загружен из файла «{doc.file_name}»")


def _is_valid_date(s: str) -> bool:
    try:
        datetime.datetime.strptime(s, "%d.%m.%Y")
        return True
    except ValueError:
        return False


async def _try_refresh_filter_menu(update: Update, context) -> None:
    """Обновляет меню фильтров если оно открыто (по сохранённому message_id)."""
    msg_id = context.user_data.get("filter_msg_id")
    if not msg_id:
        return
    data        = load_presets()
    draft       = context.user_data.get("draft", DEFAULT_FILTER)
    active_name = data.get("active", "default")
    text        = _filter_menu_text(draft, active_name)
    kb          = _filter_keyboard(draft, data["presets"])
    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
    except BadRequest:
        pass


# ── Хэндлеры: /fetch + пагинация ──────────────────────────────────────────────

async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filters = context.user_data.pop("pending_filter", None) or get_active_filter()

    if context.args:
        date_str = _parse_date_arg(context.args)
        filters["date_from"] = filters["date_to"] = date_str

    status_msg = await update.message.reply_text(
        f"🔍 Ищу закупки...\n{_filter_summary(filters)}\n\nЭто займёт 1–2 минуты.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🛑 Остановить", callback_data="fetch:stop"),
        ]]),
    )
    context.user_data["fetch_status_msg_id"] = status_msg.message_id

    stop_event = threading.Event()
    context.user_data["fetch_stop_event"] = stop_event

    loop   = asyncio.get_event_loop()
    future = loop.run_in_executor(None, _fetch_with_filters, filters, stop_event)
    context.user_data["fetch_future"] = future

    try:
        contracts = await future
    except asyncio.CancelledError:
        try:
            await status_msg.edit_text("🛑 Поиск остановлен.")
        except (BadRequest, TimedOut, NetworkError):
            pass
        return
    finally:
        context.user_data.pop("fetch_future", None)
        context.user_data.pop("fetch_stop_event", None)
        context.user_data.pop("fetch_status_msg_id", None)

    if stop_event.is_set() and not contracts:
        try:
            await status_msg.edit_text("🛑 Поиск остановлен.")
        except (BadRequest, TimedOut, NetworkError):
            pass
        return

    try:
        await status_msg.edit_text(
            f"🔍 Поиск завершён.\n{_filter_summary(filters)}",
        )
    except (BadRequest, TimedOut, NetworkError):
        pass

    if not contracts:
        await update.message.reply_text("Закупок по текущим фильтрам не найдено.")
        return

    _save_to_db(contracts)
    contracts.sort(key=lambda c: c.get("quick_score") or 0, reverse=True)

    context.user_data["results"] = contracts
    context.user_data["pg_idx"]  = 0

    await update.message.reply_text(
        f"Найдено *{len(contracts)}* закупок. Листайте кнопками ◀ ▶",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.reply_text(
        _card_text(contracts, 0),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_card_keyboard(contracts, 0),
    )


async def callback_fetch_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query      = update.callback_query
    stop_event = context.user_data.get("fetch_stop_event")
    future     = context.user_data.get("fetch_future")
    if stop_event or future:
        if stop_event:
            stop_event.set()   # сигнал парсеру остановиться между страницами
        if future:
            future.cancel()    # прекратить ожидание результата
        await _qanswer(query, "🛑 Останавливаю...")
    else:
        await _qanswer(query, "Поиск уже завершён")


def _parse_date_arg(args: list[str]) -> str:
    from datetime import datetime, timedelta
    raw = args[0].strip().lower()
    if raw in ("сегодня", "today", "0"):
        return datetime.now().strftime("%d.%m.%Y")
    if raw in ("вчера", "yesterday", "-1"):
        return (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass
    return datetime.now().strftime("%d.%m.%Y")


async def callback_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    results = context.user_data.get("results")
    if not results:
        await _qanswer(query, "⚠️ Сессия устарела — запустите /fetch заново")
        return

    idx = context.user_data.get("pg_idx", 0)
    if query.data == "pg:next":
        idx = min(idx + 1, len(results) - 1)
    elif query.data == "pg:prev":
        idx = max(idx - 1, 0)
    elif query.data == "pg:skip":
        results.pop(idx)
        context.user_data["results"] = results
        if not results:
            await _qanswer(query, "Список пуст")
            try:
                await query.edit_message_text("Все закупки просмотрены.")
            except (BadRequest, TimedOut, NetworkError):
                pass
            return
        idx = min(idx, len(results) - 1)

    context.user_data["pg_idx"] = idx
    await _qanswer(query, f"{idx + 1} / {len(results)}")

    try:
        await query.edit_message_text(
            _card_text(results, idx),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_card_keyboard(results, idx),
        )
    except (BadRequest, TimedOut, NetworkError):
        pass


# ── Хэндлеры: детальный анализ ─────────────────────────────────────────────────

PRIORITY_DOC_KEYWORDS = ["техническое задание", "тз", "описание объекта", "объект закупки", "требования"]


def _is_priority_doc(name: str) -> bool:
    nl = name.lower()
    return any(kw in nl for kw in PRIORITY_DOC_KEYWORDS)


def _docs_keyboard(contract_id: int, docs: list[dict], selected: set) -> InlineKeyboardMarkup:
    rows = []
    for i, doc in enumerate(docs):
        mark = "✅" if i in selected else "☐"
        label = f"{mark} {doc['name'][:40]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"da:toggle:{contract_id}:{i}")])
    rows.append([
        InlineKeyboardButton("🔍 Анализировать выбранные", callback_data=f"da:run:{contract_id}"),
    ])
    rows.append([
        InlineKeyboardButton("✅ Все", callback_data=f"da:all:{contract_id}"),
        InlineKeyboardButton("☐ Снять все", callback_data=f"da:none:{contract_id}"),
    ])
    return InlineKeyboardMarkup(rows)


async def callback_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except (TimedOut, NetworkError):
        pass

    contract_id = int(query.data.split(":")[1])
    contract    = get_contract(contract_id)
    if not contract:
        await query.message.reply_text("Закупка не найдена в базе.")
        return

    if contract.get("detail_text"):
        await _send_analysis(query, contract["detail_text"], contract)
        return

    status_msg = await query.message.reply_text("🔎 Получаю список документов с ЕИС...")

    loop = asyncio.get_event_loop()
    from parsers.zakupki import fetch_contract_documents
    try:
        docs = await asyncio.wait_for(
            loop.run_in_executor(None, fetch_contract_documents, contract["url"]),
            timeout=30,
        )
    except asyncio.TimeoutError:
        docs = []
        await status_msg.edit_text("⚠️ ЕИС не ответил за 30 сек. Анализирую по карточке...")

    if not docs:
        await status_msg.edit_text("Документы не найдены. Анализирую по карточке...")
        prompts  = load_prompts()
        analysis = await loop.run_in_executor(None, detailed_analysis, contract, prompts["detailed"])
        update_detail(contract_id, analysis)
        await status_msg.delete()
        await _send_analysis(query, analysis, contract)
        return

    await status_msg.delete()

    # По умолчанию отмечаем приоритетные документы, если есть — иначе все
    selected = {i for i, d in enumerate(docs) if _is_priority_doc(d["name"])}
    if not selected:
        selected = set(range(len(docs)))

    context.user_data[f"docs_{contract_id}"] = docs
    context.user_data[f"sel_{contract_id}"]  = selected

    subj = (contract.get("subject") or "")[:80]
    sel_msg = await query.message.reply_text(
        f"📋 *Документы закупки* — {len(docs)} шт.\n_{subj}_\n\nВыберите для анализа:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_docs_keyboard(contract_id, docs, selected),
    )
    context.user_data[f"sel_msg_{contract_id}"] = sel_msg.message_id


async def callback_doc_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parts = query.data.split(":")  # da:action:contract_id[:idx]
    action      = parts[1]
    contract_id = int(parts[2])

    docs     = context.user_data.get(f"docs_{contract_id}", [])
    selected = context.user_data.get(f"sel_{contract_id}", set())

    if action == "toggle":
        idx = int(parts[3])
        if idx in selected:
            selected.discard(idx)
        else:
            selected.add(idx)
        context.user_data[f"sel_{contract_id}"] = selected
        await _qanswer(query)
        try:
            await query.edit_message_reply_markup(_docs_keyboard(contract_id, docs, selected))
        except (BadRequest, TimedOut, NetworkError):
            pass

    elif action == "all":
        selected = set(range(len(docs)))
        context.user_data[f"sel_{contract_id}"] = selected
        await _qanswer(query, "✅ Выбраны все")
        try:
            await query.edit_message_reply_markup(_docs_keyboard(contract_id, docs, selected))
        except (BadRequest, TimedOut, NetworkError):
            pass

    elif action == "none":
        selected = set()
        context.user_data[f"sel_{contract_id}"] = selected
        await _qanswer(query, "Снято всё")
        try:
            await query.edit_message_reply_markup(_docs_keyboard(contract_id, docs, selected))
        except (BadRequest, TimedOut, NetworkError):
            pass

    elif action == "run":
        if not selected:
            await _qanswer(query, "⚠️ Выберите хотя бы один документ")
            return

        await _qanswer(query)
        chosen = [docs[i] for i in sorted(selected)]

        # Заменяем меню выбора на статус скачивания
        try:
            await query.edit_message_text(f"⬇️ Скачиваю {len(chosen)} документ(ов)...")
        except (BadRequest, TimedOut, NetworkError):
            pass

        contract = get_contract(contract_id)
        loop     = asyncio.get_event_loop()

        def _download_and_analyze():
            from parsers.zakupki import download_document
            number    = (contract.get("number") or f"contract_{contract_id}").replace("/", "_").replace(" ", "")
            docs_dir  = Path("data/documents") / number
            docs_dir.mkdir(parents=True, exist_ok=True)
            for doc in chosen:
                download_document(doc, docs_dir)
            contract["docs_dir"] = str(docs_dir)
            prompts = load_prompts()
            return detailed_analysis(contract, prompts["detailed"])

        analysis = await loop.run_in_executor(None, _download_and_analyze)
        update_detail(contract_id, analysis)

        # Удаляем статусное сообщение и чистим данные
        try:
            await query.message.delete()
        except (BadRequest, TimedOut, NetworkError):
            pass
        context.user_data.pop(f"docs_{contract_id}", None)
        context.user_data.pop(f"sel_{contract_id}", None)
        context.user_data.pop(f"sel_msg_{contract_id}", None)

        await _send_analysis(query, analysis, contract)


async def _send_analysis(query, analysis: str, contract: dict) -> None:
    number  = contract.get("number", "?")
    subject = (contract.get("subject") or "")[:80]
    price   = contract.get("price", "н/д")
    header  = f"📄 *{number}*\n{subject}\n💰 {price}\n\n"
    full    = header + analysis
    for i in range(0, len(full), 4000):
        chunk = full[i:i + 4000]
        kb    = None
        if i == 0:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 Открыть на ЕИС", url=contract.get("url", "https://zakupki.gov.ru"))
            ]])
        await query.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


# ── Хэндлеры: /schedule ───────────────────────────────────────────────────────

async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg     = load_bot_cfg()
    current = cfg.get("schedule_time", "не задано")

    hours = ["09", "10", "11", "12", "13", "14", "15", "16", "17", "18"]
    rows, row = [], []
    for h in hours:
        t     = f"{h}:00"
        label = f"✅ {t}" if t == current else t
        row.append(InlineKeyboardButton(label, callback_data=f"sch:{t}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Отключить", callback_data="sch:off")])

    await update.message.reply_text(
        f"⏰ *Настройка автосбора* (время МСК)\n\nТекущее: *{current}*\nВыберите новое:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def callback_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except (TimedOut, NetworkError):
        pass
    time_part = query.data[4:]  # "sch:13:00" → "13:00" или "off"

    cfg = load_bot_cfg()
    if time_part == "off":
        cfg.pop("schedule_time", None)
        save_bot_cfg(cfg)
        _cancel_daily_job(context)
        await query.edit_message_text("❌ Автосбор отключён.")
    else:
        cfg["schedule_time"] = time_part
        save_bot_cfg(cfg)
        _setup_daily_job(context, time_part, query.message.chat_id)
        await query.edit_message_text(
            f"✅ Автосбор настроен на *{time_part}* МСК ежедневно.",
            parse_mode=ParseMode.MARKDOWN,
        )


def _setup_daily_job(context, time_str: str, chat_id: int) -> None:
    jq = context.application.job_queue
    for job in jq.get_jobs_by_name("daily_fetch"):
        job.schedule_removal()
    h, m = map(int, time_str.split(":"))
    jq.run_daily(
        _daily_fetch_job,
        time=datetime.time(h, m, tzinfo=MSK),
        name="daily_fetch",
        chat_id=chat_id,
    )


def _cancel_daily_job(context) -> None:
    for job in context.application.job_queue.get_jobs_by_name("daily_fetch"):
        job.schedule_removal()


async def _daily_fetch_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    import daily_run
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, daily_run.main)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)):
        return  # сетевые флуктуации — не логируем
    print(f"[ERROR] {type(err).__name__}: {err}")


# ── Хэндлеры: /watch ──────────────────────────────────────────────────────────

WATCH_INTERVALS = [1, 2, 4, 6, 12, 24]


def _watch_list_keyboard(watches: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for w in watches:
        status = "🟢" if w["active"] else "⏸"
        rows.append([
            InlineKeyboardButton(f"{status} {w['name']}", callback_data=f"wt:info:{w['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"wt:del:{w['id']}"),
        ])
    rows.append([InlineKeyboardButton("➕ Новый вотч", callback_data="wt:new")])
    return InlineKeyboardMarkup(rows)


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    watches = list_watches(chat_id)
    if watches:
        text = f"👁 *Мониторинг закупок*\n\nАктивных вотчей: {len(watches)}\nВыберите или создайте новый:"
    else:
        text = "👁 *Мониторинг закупок*\n\nВотчей пока нет. Создайте первый — он будет автоматически проверять новые закупки по вашим фильтрам."
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_watch_list_keyboard(watches),
    )


async def callback_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _qanswer(query)
    parts    = query.data.split(":", 2)
    sub      = parts[1]
    chat_id  = query.message.chat_id

    if sub == "new":
        data        = load_presets()
        active_name = data.get("active", "default")
        active_flt  = data["presets"].get(active_name, DEFAULT_FILTER)
        context.user_data["watch_draft_filter"] = deepcopy(active_flt)
        context.user_data["watch_draft_name"]   = active_name

        rows = [[InlineKeyboardButton(f"{h}ч", callback_data=f"wt:interval:{h}")] for h in WATCH_INTERVALS]
        await query.edit_message_text(
            f"➕ *Новый вотч*\n\n"
            f"Будут использованы текущие фильтры пресета *{active_name}*:\n"
            f"{_filter_summary(active_flt)}\n\n"
            f"Как часто проверять новые закупки?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"{h}ч", callback_data=f"wt:interval:{h}") for h in WATCH_INTERVALS]],
            ),
        )

    elif sub == "interval":
        interval_h  = int(parts[2])
        flt         = context.user_data.get("watch_draft_filter", deepcopy(DEFAULT_FILTER))
        name        = context.user_data.get("watch_draft_name", "вотч")
        watch_id    = add_watch(name, flt, interval_h, chat_id)
        _schedule_watch(context.application, watch_id, interval_h, chat_id)

        await query.edit_message_text(
            f"✅ *Вотч «{name}» создан*\n\n"
            f"Проверка каждые {interval_h}ч.\n"
            f"{_filter_summary(flt)}\n\n"
            f"Буду присылать уведомления когда появятся новые закупки.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif sub == "info":
        watch_id = int(parts[2])
        w        = get_watch(watch_id)
        if not w:
            await query.edit_message_text("Вотч не найден.")
            return
        last = w.get("last_run") or "ещё не запускался"
        await query.edit_message_text(
            f"👁 *{w['name']}*\n\n"
            f"{_filter_summary(w['filters'])}\n\n"
            f"Интервал: каждые {w['interval_h']}ч\n"
            f"Последняя проверка: {last}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 Удалить", callback_data=f"wt:del:{watch_id}"),
                InlineKeyboardButton("← Назад",   callback_data="wt:back"),
            ]]),
        )

    elif sub == "del":
        watch_id = int(parts[2])
        w        = get_watch(watch_id)
        name     = w["name"] if w else "?"
        delete_watch(watch_id)
        _cancel_watch(context.application, watch_id)
        watches = list_watches(chat_id)
        await query.edit_message_text(
            f"🗑 Вотч «{name}» удалён.\n\nАктивных вотчей: {len(watches)}",
            reply_markup=_watch_list_keyboard(watches),
        )

    elif sub == "back":
        watches = list_watches(chat_id)
        await query.edit_message_text(
            f"👁 *Мониторинг закупок*\n\nАктивных вотчей: {len(watches)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_watch_list_keyboard(watches),
        )


def _watch_job_name(watch_id: int) -> str:
    return f"watch_{watch_id}"


def _schedule_watch(app, watch_id: int, interval_h: int, chat_id: int) -> None:
    jq = app.job_queue
    if jq is None:
        return
    for job in jq.get_jobs_by_name(_watch_job_name(watch_id)):
        job.schedule_removal()
    jq.run_repeating(
        _watch_check_job,
        interval=interval_h * 3600,
        first=60,
        name=_watch_job_name(watch_id),
        chat_id=chat_id,
        data={"watch_id": watch_id},
    )


def _cancel_watch(app, watch_id: int) -> None:
    for job in app.job_queue.get_jobs_by_name(_watch_job_name(watch_id)):
        job.schedule_removal()


async def _watch_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    watch_id = context.job.data["watch_id"]
    chat_id  = context.job.chat_id
    w        = get_watch(watch_id)
    if not w:
        return

    loop      = asyncio.get_event_loop()
    contracts = await loop.run_in_executor(None, _fetch_with_filters, w["filters"])
    if not contracts:
        touch_watch(watch_id)
        return

    new_ones = []
    for c in contracts:
        from data.db import get_conn
        with get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM contracts WHERE number=?", (c.get("number", ""),)
            ).fetchone()
        if not exists:
            db_id = upsert_contract({
                "number":   c.get("number",   ""),
                "subject":  c.get("subject",  ""),
                "price":    c.get("price",    ""),
                "customer": c.get("customer", ""),
                "url":      c.get("url",      ""),
            })
            c["_db_id"] = db_id
            new_ones.append(c)

    touch_watch(watch_id)

    if not new_ones:
        return

    header = (
        f"🔔 *Вотч «{w['name']}»* — {len(new_ones)} новых закупок!\n\n"
    )
    await context.bot.send_message(chat_id, header, parse_mode=ParseMode.MARKDOWN)

    for c in new_ones[:5]:
        subj  = " ".join((c.get("subject") or "Предмет не указан").split())[:150]
        price = (c.get("price") or "н/д").strip()
        cust  = (c.get("customer") or "").strip()[:80]
        db_id = c.get("_db_id")
        url   = c.get("url", "https://zakupki.gov.ru")

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔍 Анализ", callback_data=f"detail:{db_id}") if db_id else
            InlineKeyboardButton("🔗 Открыть", url=url),
            InlineKeyboardButton("🔗 Открыть", url=url),
        ]])
        await context.bot.send_message(
            chat_id,
            f"*{subj}*\n💰 {price}\n🏛 {cust}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )

    if len(new_ones) > 5:
        await context.bot.send_message(
            chat_id,
            f"_...и ещё {len(new_ones) - 5}. Запустите /fetch чтобы увидеть все._",
            parse_mode=ParseMode.MARKDOWN,
        )


# ── Хэндлеры: /prompt ─────────────────────────────────────────────────────────

DEFAULT_DETAILED_PROMPT = (
    "Ты — эксперт по государственным закупкам (44-ФЗ). Проанализируй документы закупки и дай структурированный ответ:\n\n"
    "1. **Предмет контракта** — что именно требуется (1-2 предложения)\n"
    "2. **Ключевые требования** — технические, квалификационные, опыт, лицензии\n"
    "3. **Риски и сложности** — что может быть проблемой для участника\n"
    "4. **Оценка реалистичности НМЦ** — завышена, занижена или нормальная\n"
    "5. **Конкурентная среда** — насколько вероятна сильная конкуренция\n"
    "6. **Рекомендация** — стоит ли участвовать (да/нет/требует изучения) и конкретные следующие шаги\n\n"
    "---\n\nДОКУМЕНТЫ ЗАКУПКИ:\n{documents_text}"
)


def _prompt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Изменить",          callback_data="pr:edit"),
            InlineKeyboardButton("🔄 Сбросить к дефолту", callback_data="pr:reset"),
        ]
    ])


async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompts = load_prompts()
    current = prompts.get("detailed", DEFAULT_DETAILED_PROMPT)
    preview = current[:800] + ("…" if len(current) > 800 else "")
    await update.message.reply_text(
        "📝 *Промпт детального анализа*",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.reply_text(
        preview,
        reply_markup=_prompt_keyboard(),
    )


async def callback_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _qanswer(query)
    action = query.data.split(":")[1]

    if action == "edit":
        context.user_data["await_input"]      = "prompt_detailed"
        context.user_data["prompt_msg_id"]    = query.message.message_id
        await query.message.reply_text(
            "Введите новый промпт для детального анализа — текстом или прикрепите .txt файл.\n"
            "Текст документов закупки будет подставлен в конец автоматически.\n\n"
            "Отправьте `-` чтобы сбросить к дефолту.",
        )

    elif action == "reset":
        prompts = load_prompts()
        prompts["detailed"] = DEFAULT_DETAILED_PROMPT
        with open(PROMPTS_PATH, "w", encoding="utf-8") as f:
            json.dump(prompts, f, ensure_ascii=False, indent=2)
        preview = DEFAULT_DETAILED_PROMPT[:800] + ("…" if len(DEFAULT_DETAILED_PROMPT) > 800 else "")
        try:
            await query.edit_message_text("✅ *Промпт сброшен к дефолту*", parse_mode=ParseMode.MARKDOWN)
        except (BadRequest, TimedOut, NetworkError):
            pass
        await query.message.reply_text(preview, reply_markup=_prompt_keyboard())


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    MENU_COMMANDS.update({
        "🔍 Поиск":       cmd_fetch,
        "⚙️ Фильтры":     cmd_filters,
        "👁 Мониторинг":  cmd_watch,
        "📝 Промпт":      cmd_prompt,
        "⏰ Расписание":  cmd_schedule,
        "📊 Статус":      cmd_status,
        "❓ Помощь":      cmd_help,
    })
    init_db()
    cfg   = load_bot_cfg()
    token = cfg.get("token", "")

    if not token or token == "ВСТАВЬ_ТОКЕН_СЮДА":
        print("Токен не задан в config/bot_config.json")
        return

    proxy = cfg.get("proxy", "").strip() or None

    # Увеличенные таймауты для работы через прокси
    req_kwargs = dict(read_timeout=20, write_timeout=20, connect_timeout=15)

    builder = Application.builder().token(token)
    if proxy:
        req = HTTPXRequest(proxy=proxy, httpx_kwargs={"verify": False}, **req_kwargs)
        upd = HTTPXRequest(proxy=proxy, httpx_kwargs={"verify": False}, **req_kwargs)
        builder = builder.request(req).get_updates_request(upd)
        print(f"Прокси: {proxy}")
    else:
        req = HTTPXRequest(httpx_kwargs={"trust_env": False}, **req_kwargs)
        builder = builder.request(req).get_updates_request(
            HTTPXRequest(httpx_kwargs={"trust_env": False}, **req_kwargs)
        )

    app = builder.build()

    # Восстанавливаем расписание из сохранённого конфига
    sched_time = cfg.get("schedule_time")
    if sched_time and cfg.get("chat_id"):
        if app.job_queue is None:
            print("ПРЕДУПРЕЖДЕНИЕ: job_queue недоступен — установите apscheduler: pip install 'python-telegram-bot[job-queue]'")
        else:
            h, m = map(int, sched_time.split(":"))
            app.job_queue.run_daily(
                _daily_fetch_job,
                time=datetime.time(h, m, tzinfo=MSK),
                name="daily_fetch",
                chat_id=cfg["chat_id"],
            )
            print(f"Автосбор восстановлен: {sched_time} МСК")

    # Восстанавливаем активные вотчи
    for w in get_all_active_watches():
        _schedule_watch(app, w["id"], w["interval_h"], w["chat_id"])
        print(f"Вотч восстановлен: «{w['name']}» каждые {w['interval_h']}ч")

    # Хэндлеры команд
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("fetch",    cmd_fetch))
    app.add_handler(CommandHandler("filters",  cmd_filters))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("prompt",   cmd_prompt))
    app.add_handler(CommandHandler("watch",    cmd_watch))
    app.add_handler(CommandHandler("restart",  cmd_restart))
    app.add_handler(CommandHandler("help",     cmd_help))

    # Хэндлеры callback-кнопок
    app.add_handler(CallbackQueryHandler(callback_filter,   pattern=r"^f:"))
    app.add_handler(CallbackQueryHandler(callback_preset,   pattern=r"^ps:"))
    app.add_handler(CallbackQueryHandler(callback_page,     pattern=r"^pg:"))
    app.add_handler(CallbackQueryHandler(callback_detail,     pattern=r"^detail:\d+$"))
    app.add_handler(CallbackQueryHandler(callback_doc_select, pattern=r"^da:"))
    app.add_handler(CallbackQueryHandler(callback_schedule, pattern=r"^sch:"))
    app.add_handler(CallbackQueryHandler(callback_prompt,   pattern=r"^pr:"))
    app.add_handler(CallbackQueryHandler(callback_watch,    pattern=r"^wt:"))
    app.add_handler(CallbackQueryHandler(callback_help,       pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(callback_fetch_stop, pattern=r"^fetch:stop$"))

    # Хэндлер текстовых ответов (ввод параметров фильтров)
    app.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, handle_text_input))
    app.add_handler(MessageHandler(tg_filters.Document.ALL, handle_document_input))

    app.add_error_handler(error_handler)

    print("Бот запущен. /start в Telegram чтобы зарегистрировать chat_id.")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

    # run_polling вернул управление — значит был вызван stop_running() из /restart
    os.execv(sys.executable, [sys.executable] + sys.argv)


if __name__ == "__main__":
    main()
