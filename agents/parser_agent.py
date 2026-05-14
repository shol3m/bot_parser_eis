"""
Агент парсинга закупок с zakupki.gov.ru.

CLI:
    python agents/parser_agent.py --filters config/filters.json
    python agents/parser_agent.py --filters '{"law":"44","date_from":"today"}'
    python agents/parser_agent.py --filters config/filters.json --pages 3

Import:
    from agents.parser_agent import run
    contracts = run(filters, max_pages=0, stop_event=None)
"""

import sys
import json
import argparse
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.zakupki import run as _parse


def run(filters: dict, max_pages: int = 0, stop_event: threading.Event | None = None) -> list[dict]:
    """
    Запускает парсер с переданными фильтрами.

    filters:
        law           — "44" | "223" | "both"
        keywords      — список строк
        okpd2_section — раздел ОКПД2, например "J"
        okpd2_key     — числовой ключ ОКПД2
        region_codes  — список кодов регионов
        price_from    — минимальная НМЦ
        price_to      — максимальная НМЦ
        date_from     — "today" | "yesterday" | "ДД.ММ.ГГГГ"
        date_to       — "today" | "yesterday" | "ДД.ММ.ГГГГ"

    Возвращает список закупок:
        [{"number", "subject", "price", "customer", "url",
          "date_updated", "date_end", "_law"}, ...]
    """
    import tempfile
    import os

    if filters.get("law") == "both":
        combined, seen = [], set()
        for law_val in ("44", "223"):
            if stop_event and stop_event.is_set():
                break
            result = _run_single(dict(filters, law=law_val), max_pages, stop_event)
            for c in result:
                key = c.get("number") or c.get("url", "")
                if key not in seen:
                    seen.add(key)
                    c["_law"] = law_val
                    combined.append(c)
        return combined

    return _run_single(filters, max_pages, stop_event)


def _run_single(filters: dict, max_pages: int, stop_event) -> list[dict]:
    import tempfile
    import os

    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="_parser_", dir="config")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(filters, fp, ensure_ascii=False)
        results = _parse(config_path=tmp_path, max_pages=max_pages, stop_event=stop_event)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    law = filters.get("law", "44")
    for r in results:
        r.setdefault("_law", law)
    return results


def _load_filters(source: str) -> dict:
    """Принимает путь к JSON-файлу или JSON-строку."""
    path = Path(source)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(source)


def main():
    parser = argparse.ArgumentParser(description="Агент парсинга zakupki.gov.ru")
    parser.add_argument("--filters", required=True, help="Путь к JSON-файлу или JSON-строка с фильтрами")
    parser.add_argument("--pages", type=int, default=0, help="Макс. страниц (0 = все)")
    parser.add_argument("--out", help="Путь для сохранения результата (по умолчанию — stdout)")
    args = parser.parse_args()

    filters = _load_filters(args.filters)
    contracts = run(filters, max_pages=args.pages)

    output = json.dumps(contracts, ensure_ascii=False, indent=2)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Сохранено: {args.out} ({len(contracts)} закупок)")
    else:
        print(output)


if __name__ == "__main__":
    main()
