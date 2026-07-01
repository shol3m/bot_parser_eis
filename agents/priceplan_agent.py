"""
Агент парсинга запросов цены товаров и услуг (раздел «Планирование» на zakupki.gov.ru).

CLI:
    python agents/priceplan_agent.py --filters config/priceplan_filter.json

Import:
    from agents.priceplan_agent import run
    results = run(filters, max_pages=0, stop_event=None, progress_cb=None)
"""

import sys
import json
import argparse
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.priceplan import run as _parse

_PROJECT_ROOT = Path(__file__).parent.parent


def _load_proxy() -> str | None:
    """Читает прокси: ZAKUPKI_PROXY из env/.env → proxy из bot_config.json."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(_PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass
    env_proxy = os.environ.get("ZAKUPKI_PROXY", "").strip()
    if env_proxy:
        return env_proxy
    cfg_path = _PROJECT_ROOT / "config" / "bot_config.json"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f).get("proxy", "").strip() or None
    except Exception:
        return None


def run(filters: dict,
        max_pages: int = 0,
        stop_event: threading.Event | None = None,
        progress_cb=None) -> list[dict]:
    import tempfile, os

    proxy = _load_proxy()
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="_priceplan_", dir="config")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(filters, fp, ensure_ascii=False)
        results = _parse(config_path=tmp_path, max_pages=max_pages,
                         stop_event=stop_event, progress_cb=progress_cb, proxy=proxy)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    for r in results:
        r.setdefault("_section", "priceplan")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--filters", default="config/priceplan_filter.json")
    parser.add_argument("--pages", type=int, default=0)
    args = parser.parse_args()

    with open(args.filters, encoding="utf-8") as f:
        filters = json.load(f)

    results = run(filters, max_pages=args.pages)
    print(json.dumps(results, ensure_ascii=False, indent=2))
