"""
Парсер раздела «Запросы цен товаров, работ, услуг» zakupki.gov.ru
(https://zakupki.gov.ru/epz/pricereq/search/results.html).
"""

import time
import json
import re
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

BASE_URL   = "https://zakupki.gov.ru"
SEARCH_URL = "https://zakupki.gov.ru/epz/pricereq/search/results.html"
PROXY      = {"http": None, "https": None}
SESSION    = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://zakupki.gov.ru",
})


def _resolve_date(value: str | None) -> str | None:
    if not value:
        return None
    if value == "today":
        return datetime.now().strftime("%d.%m.%Y")
    if value == "yesterday":
        from datetime import timedelta
        return (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
    return value


def _get(url: str, params: dict | None = None) -> requests.Response | None:
    try:
        r = SESSION.get(url, params=params, proxies=PROXY, timeout=30, verify=False)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  [pricereq] Ошибка запроса: {e}")
        return None


def build_priceplan_params(filters: dict, page: int = 1) -> dict:
    params = {
        "morphology":         "on",
        "pageNumber":         page,
        "sortDirection":      "false",
        "recordsPerPage":     "_10",
        "showLotsInfoHidden": "false",
        "sortBy":             "UPDATE_DATE",
    }

    # Статус запроса (можно несколько)
    statuses = filters.get("statuses", ["published", "proposed", "ended"])
    for s in statuses:
        if s in ("published", "proposed", "ended"):
            params[s] = "on"

    # Ключевые слова / объект закупки
    if filters.get("keywords"):
        params["searchString"] = " ".join(filters["keywords"])

    # Заказчик (наименование или ИНН)
    if filters.get("customer_inn"):
        params["customerTitle"] = filters["customer_inn"].strip()

    # Регион заказчика
    region_codes = filters.get("region_codes", [])
    if region_codes:
        params["customerPlace"] = region_codes[0]
        if len(region_codes) > 1:
            params["customerPlaceCodes"] = ",".join(str(c) for c in region_codes)

    # Дата
    date_from = _resolve_date(filters.get("date_from"))
    date_to   = _resolve_date(filters.get("date_to"))
    date_type = filters.get("date_type", "published")

    if date_type == "updated":
        if date_from: params["updateDateFrom"] = date_from
        if date_to:   params["updateDateTo"]   = date_to
    else:
        if date_from: params["publishDateFrom"] = date_from
        if date_to:   params["publishDateTo"]   = date_to

    return params


def get_total_pages(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    nums = []
    for li in soup.select("ul.pages li"):
        try:
            nums.append(int(li.text.strip()))
        except ValueError:
            pass
    if nums:
        return max(nums)
    for el in soup.select("div, span"):
        m = re.search(r"из\s+([\d\s]+)", el.text.strip())
        if m:
            total = int(m.group(1).replace(" ", ""))
            return max(1, (total + 9) // 10)
    return 1


def parse_priceplan_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    cards = soup.select("div.search-registry-entry-block")
    if not cards:
        cards = soup.select("div.registry-entry__form")

    for card in cards:
        try:
            item = {}

            num_el = card.select_one("div.registry-entry__header-mid__number a")
            if not num_el:
                num_el = card.select_one("a[href*='pricereq']")
            if num_el:
                item["number"] = num_el.text.strip()
                href = num_el.get("href", "")
                item["url"] = f"{BASE_URL}{href}" if href.startswith("/") else href

            subj_el = card.select_one("div.registry-entry__body-value")
            if subj_el:
                item["subject"] = subj_el.text.strip()

            cust_el = card.select_one("div.registry-entry__body-href a")
            if cust_el:
                item["customer"] = cust_el.text.strip()

            # Статус (Опубликован / Предложения поданы / Завершён)
            status_el = card.select_one("span.registry-entry__header-mid__title")
            if not status_el:
                status_el = card.select_one("div.registry-entry__header-top__icon span")
            if status_el:
                item["status"] = status_el.text.strip()

            date_map = {}
            for block in card.select("div.data-block"):
                title_el = block.select_one(".data-block__title")
                value_el = block.select_one(".data-block__value")
                if title_el and value_el:
                    key = title_el.text.strip().lower()
                    val = value_el.text.strip()
                    if "размещ" in key:
                        date_map["date_placement"] = val
                    elif "окончан" in key or "подач" in key or "заявк" in key or "предлож" in key:
                        date_map["date_end"] = val
                    elif "обновл" in key or "измен" in key:
                        date_map["date_updated"] = val
                    elif "ответ" in key or "предоставл" in key:
                        date_map["date_response"] = val
            if not date_map:
                vals = card.select("div.data-block__value")
                if vals:
                    date_map["date_placement"] = vals[0].text.strip()
                if len(vals) > 1:
                    date_map["date_end"] = vals[1].text.strip()
            item.update(date_map)

            item["price"] = ""
            item["_section"] = "priceplan"

            if "number" in item or "subject" in item:
                results.append(item)

        except Exception as e:
            print(f"  [pricereq] Ошибка карточки: {e}")

    return results


def run(config_path: str = "config/priceplan_filter.json",
        max_pages: int = 0,
        stop_event=None,
        progress_cb=None) -> list[dict]:
    with open(config_path, encoding="utf-8") as f:
        filters = json.load(f)

    date_label = _resolve_date(filters.get("date_from")) or "все даты"
    statuses   = filters.get("statuses", ["published", "proposed", "ended"])
    print(f"[pricereq] Поиск: дата: {date_label} | статус: {statuses}")

    print("[pricereq] Страница 1... ", end="", flush=True)
    html = _get(SEARCH_URL, build_priceplan_params(filters, 1))
    if not html:
        return []

    debug_path = Path(__file__).parent.parent / "data" / "debug_priceplan.html"
    try:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(html.text, encoding="utf-8")
    except Exception:
        pass

    page_results = parse_priceplan_results(html.text)
    all_results  = list(page_results)
    total_pages  = get_total_pages(html.text)
    if max_pages:
        total_pages = min(total_pages, max_pages)
    print(f"{len(page_results)} записей | страниц: {total_pages}")
    if progress_cb:
        try:
            progress_cb(len(all_results), 1, total_pages)
        except Exception:
            pass

    for page in range(2, total_pages + 1):
        if stop_event and stop_event.is_set():
            print("[pricereq] Остановлено.")
            break
        time.sleep(1.2)
        print(f"[pricereq] Страница {page}/{total_pages}... ", end="", flush=True)
        resp = _get(SEARCH_URL, build_priceplan_params(filters, page))
        if not resp:
            break
        page_results = parse_priceplan_results(resp.text)
        if not page_results:
            print("пусто, стоп")
            break
        all_results.extend(page_results)
        print(f"{len(page_results)} записей")
        if progress_cb:
            try:
                progress_cb(len(all_results), page, total_pages)
            except Exception:
                pass

    print(f"[pricereq] Итого: {len(all_results)} запросов цены")
    return all_results
