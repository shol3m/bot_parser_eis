"""
Оркестратор агентной системы госзакупок.
Координирует parser_agent → analyze_agent, вызывается ботом.
"""

import threading
from pathlib import Path

from agents.parser_agent import run as parse
from agents.analyze_agent import run as analyze
from data.db import update_detail


def fetch_contracts(
    filters: dict,
    max_pages: int = 0,
    stop_event: threading.Event | None = None,
) -> list[dict]:
    """Шаг 1: парсинг закупок. Возвращает список закупок без записи в БД."""
    return parse(filters, max_pages=max_pages, stop_event=stop_event)


def analyze_contract(
    contract: dict,
    doc_paths: list[Path | str],
    prompt: str,
    timeout: int = 120,
) -> str:
    """
    Шаг 2: анализ документов закупки.
    Сохраняет результат в БД, возвращает текст анализа.
    """
    result = analyze(docs=doc_paths, prompt=prompt, timeout=timeout)

    db_id = contract.get("_db_id") or contract.get("id")
    if db_id is not None:
        update_detail(int(db_id), result)

    return result
