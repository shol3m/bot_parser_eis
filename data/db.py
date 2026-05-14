"""SQLite хранилище для контрактов и результатов анализа."""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "state.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contracts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                number      TEXT UNIQUE,
                subject     TEXT,
                price       TEXT,
                customer    TEXT,
                url         TEXT,
                date_found  TEXT,
                quick_score INTEGER,
                quick_comment TEXT,
                docs_dir    TEXT,
                detail_text TEXT,
                tg_message_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS watches (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                interval_h   INTEGER NOT NULL DEFAULT 4,
                chat_id      INTEGER NOT NULL,
                active       INTEGER NOT NULL DEFAULT 1,
                last_run     TEXT
            );
        """)


def upsert_contract(data: dict) -> int:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO contracts (number, subject, price, customer, url, date_found)
            VALUES (:number, :subject, :price, :customer, :url, date('now'))
            ON CONFLICT(number) DO UPDATE SET
                subject = excluded.subject,
                price   = excluded.price
        """, data)
        row = conn.execute("SELECT id FROM contracts WHERE number=?", (data["number"],)).fetchone()
        if row is None:
            raise RuntimeError(f"upsert_contract: запись не найдена после вставки: {data['number']}")
        return row["id"]


def update_quick(contract_id: int, score: int, comment: str, docs_dir: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE contracts SET quick_score=?, quick_comment=?, docs_dir=? WHERE id=?",
            (score, comment, docs_dir, contract_id)
        )


def update_detail(contract_id: int, text: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE contracts SET detail_text=? WHERE id=?", (text, contract_id))


def update_tg_message_id(contract_id: int, msg_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE contracts SET tg_message_id=? WHERE id=?", (msg_id, contract_id))


def get_contract(contract_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM contracts WHERE id=?", (contract_id,)).fetchone()
        return dict(row) if row else None


def add_watch(name: str, filters: dict, interval_h: int, chat_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO watches (name, filters_json, interval_h, chat_id) VALUES (?,?,?,?)",
            (name, json.dumps(filters, ensure_ascii=False), interval_h, chat_id),
        )
        return cur.lastrowid


def list_watches(chat_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watches WHERE chat_id=? ORDER BY id", (chat_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["filters"] = json.loads(d["filters_json"])
            except (json.JSONDecodeError, TypeError):
                d["filters"] = {}
            result.append(d)
        return result


def get_watch(watch_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["filters"] = json.loads(d["filters_json"])
        except (json.JSONDecodeError, TypeError):
            d["filters"] = {}
        return d


def delete_watch(watch_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watches WHERE id=?", (watch_id,))


def touch_watch(watch_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE watches SET last_run=datetime('now') WHERE id=?", (watch_id,)
        )


def get_all_active_watches() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watches WHERE active=1"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["filters"] = json.loads(d["filters_json"])
            except (json.JSONDecodeError, TypeError):
                d["filters"] = {}
            result.append(d)
        return result


def get_top_contracts(min_score: int, top_n: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM contracts
            WHERE quick_score >= ? AND date_found = date('now')
            ORDER BY quick_score DESC
            LIMIT ?
        """, (min_score, top_n)).fetchall()
        return [dict(r) for r in rows]
