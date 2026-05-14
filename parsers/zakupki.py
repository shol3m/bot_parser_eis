"""
Парсер закупок с zakupki.gov.ru (ЕИС, 44-ФЗ/223-ФЗ).
Системный прокси отключается явно — он ломает TLS с этим сервером.
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

BASE_SEARCH_URL = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
BASE_URL = "https://zakupki.gov.ru"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://zakupki.gov.ru",
}

NO_PROXY = {"http": None, "https": None}


def _resolve_date(value: str | None) -> str | None:
    if not value:
        return None
    if value == "today":
        return datetime.now().strftime("%d.%m.%Y")
    if value == "yesterday":
        from datetime import timedelta
        return (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
    return value


def build_search_params(filters: dict, page: int = 1) -> dict:
    params = {
        "morphology": "on",
        "pageNumber": page,
        "sortDirection": "false",
        "recordsPerPage": "_10",
        "showLotsInfoHidden": "false",
        "sortBy": "UPDATE_DATE",
    }

    law = filters.get("law", "44")
    if law == "44":
        params["fz44"] = "on"
    elif law == "223":
        params["fz223"] = "on"
    elif law == "both":
        params["fz44"] = "on"
        params["fz223"] = "on"

    if filters.get("keywords"):
        params["searchString"] = " ".join(filters["keywords"])

    if filters.get("price_from") is not None:
        params["priceFromGeneral"] = filters["price_from"]
    if filters.get("price_to") is not None:
        params["priceToGeneral"] = filters["price_to"]

    if filters.get("okpd2_key"):
        params["okpd2Ids"] = filters["okpd2_key"]
        params["okpd2IdsWithNested"] = "on"

    for code in filters.get("region_codes", []):
        params.setdefault("af:customerPlace", []).append(code)

    date_from = _resolve_date(filters.get("date_from"))
    date_to = _resolve_date(filters.get("date_to"))
    if date_from:
        params["publishDateFrom"] = date_from
    if date_to:
        params["publishDateTo"] = date_to

    return params


def _get(url: str, params: dict | None = None) -> requests.Response | None:
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=45, proxies=NO_PROXY)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        print(f"  Ошибка запроса {url}: {e}")
        return None


def get_total_pages(html: str) -> int:
    """Читает общее количество страниц из HTML результатов поиска."""
    import re
    soup = BeautifulSoup(html, "lxml")

    # ul.pages li — содержит числа и "..."; берём максимальное число
    nums = []
    for li in soup.select("ul.pages li"):
        try:
            nums.append(int(li.text.strip()))
        except ValueError:
            pass
    if nums:
        return max(nums)

    # Запасной: ищем общее количество результатов в тексте страницы
    for el in soup.select("div, span"):
        text = el.text.strip()
        m = re.search(r"из\s+([\d\s]+)", text)
        if m:
            total = int(m.group(1).replace(" ", ""))
            return max(1, (total + 9) // 10)

    return 1


def parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    for card in soup.select("div.search-registry-entry-block"):
        try:
            item = {}

            num_el = card.select_one("div.registry-entry__header-mid__number a")
            if num_el:
                item["number"] = num_el.text.strip()
                href = num_el.get("href", "")
                item["url"] = f"{BASE_URL}{href}" if href.startswith("/") else href

            subject_el = card.select_one("div.registry-entry__body-value")
            if subject_el:
                item["subject"] = subject_el.text.strip()

            price_el = card.select_one("div.price-block__value")
            if price_el:
                item["price"] = price_el.text.strip()

            customer_el = card.select_one("div.registry-entry__body-href a")
            if customer_el:
                item["customer"] = customer_el.text.strip()

            date_blocks = card.select("div.data-block__value")
            if date_blocks:
                item["date_updated"] = date_blocks[0].text.strip()
            if len(date_blocks) > 1:
                item["date_end"] = date_blocks[1].text.strip()

            if "number" in item or "subject" in item:
                results.append(item)

        except Exception as e:
            print(f"  Ошибка парсинга карточки: {e}")

    return results


SKIP_URLS = {"zakupki-traffic.xlsx", "rpt/cat02", "listModal.html"}  # мусорные ссылки сайта


def _contract_docs_url(contract_url: str) -> str:
    """Возвращает URL вкладки 'Документы' для страницы закупки."""
    return contract_url.replace("common-info.html", "documents.html")


FILE_MARKERS = ["filestore", "download", "/file.", ".pdf", ".doc", ".zip", ".xls", ".rar"]


NAV_LABELS = {"информация и документы", "документы", "сведения", "перейти", "скачать", "открыть"}


def _extract_docs_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    docs, seen_urls = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(skip in href for skip in SKIP_URLS):
            continue
        if not any(m in href.lower() for m in FILE_MARKERS):
            continue
        url = f"{BASE_URL}{href}" if href.startswith("/") else href
        if url in seen_urls:
            continue
        seen_urls.add(url)
        name = a.text.strip()
        # Пропускаем навигационные метки и слишком короткие названия
        if not name or name.lower() in NAV_LABELS or len(name) < 4:
            name = Path(href).name or "document"
        docs.append({"name": name[:120], "url": url})
    return docs


def fetch_contract_documents(contract_url: str) -> list[dict]:
    """
    Возвращает список документов закупки.
    Пробует вкладку documents.html, при неудаче — common-info.html.
    """
    docs_url = _contract_docs_url(contract_url)

    # Пробуем страницу документов
    r = _get(docs_url)
    if r:
        docs = _extract_docs_from_html(r.text)
        if docs:
            return docs

    # Fallback: common-info.html (для 223-ФЗ и нестандартных URL)
    if docs_url != contract_url:
        r2 = _get(contract_url)
        if r2:
            return _extract_docs_from_html(r2.text)

    return []


def download_document(doc: dict, out_dir: Path) -> Path | None:
    """Скачивает один документ, возвращает путь к файлу."""
    r = _get(doc["url"])
    if not r:
        return None

    # Определяем расширение из Content-Disposition или URL
    ext = ".pdf"
    cd = r.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        fname = cd.split("filename=")[-1].strip().strip('"\'')
        ext = Path(fname).suffix or ext
    else:
        for e in [".pdf", ".docx", ".doc", ".xlsx", ".xls"]:
            if e in doc["url"].lower():
                ext = e
                break

    # Безопасное имя файла: только ASCII буквы/цифры, пробел, точка, дефис
    import unicodedata
    normalized = unicodedata.normalize("NFKC", doc["name"])
    safe_name = "".join(c for c in normalized if c.isascii() and (c.isalnum() or c in " ._-"))[:60].strip(". ")
    if not safe_name:
        safe_name = "document"
    for known_ext in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".rtf", ".txt", ".zip", ".rar"):
        if safe_name.lower().endswith(known_ext):
            safe_name = safe_name[:-len(known_ext)].strip(". ")
            break
    filepath = out_dir / f"{safe_name}{ext}"

    # Не скачиваем если уже есть
    if filepath.exists():
        return filepath

    with open(filepath, "wb") as f:
        f.write(r.content)
    return filepath


def save_results(results: list[dict], filters: dict) -> Path:
    out_dir = Path(__file__).parent.parent / "data" / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = out_dir / f"contracts_{timestamp}.json"
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "filters_used": filters,
        "total_found": len(results),
        "contracts": results,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filepath


def run(config_path: str = "config/filters.json", max_pages: int = 0, download_docs: bool = False, stop_event=None) -> list[dict]:
    """
    Основная функция.
    max_pages=0 — обходить все страницы автоматически.
    download_docs=True — скачивать документы к каждой закупке.
    stop_event — threading.Event; если установлен, парсер останавливается между страницами.
    """
    with open(config_path, encoding="utf-8") as f:
        filters = json.load(f)

    date_label = _resolve_date(filters.get("date_from")) or "все даты"
    print(f"Поиск: ОКПД2 раздел {filters.get('okpd2_section','?')} | дата: {date_label} | 44-ФЗ")

    # Первая страница — определяем сколько всего страниц
    print("Страница 1... ", end="", flush=True)
    html = _get(BASE_SEARCH_URL, build_search_params(filters, 1))
    if not html:
        return []
    html_text = html.text

    page_results = parse_results(html_text)
    all_results = list(page_results)
    total_pages = get_total_pages(html_text)
    if max_pages:
        total_pages = min(total_pages, max_pages)
    print(f"{len(page_results)} записей | всего страниц: {total_pages}")

    # Остальные страницы
    for page in range(2, total_pages + 1):
        if stop_event and stop_event.is_set():
            print("Поиск остановлен пользователем.")
            break
        time.sleep(1.2)
        print(f"Страница {page}/{total_pages}... ", end="", flush=True)
        resp = _get(BASE_SEARCH_URL, build_search_params(filters, page))
        if not resp:
            break
        page_results = parse_results(resp.text)
        if not page_results:
            print("пусто, стоп")
            break
        all_results.extend(page_results)
        print(f"{len(page_results)} записей")

    print(f"\nВсего собрано: {len(all_results)} закупок")

    # Скачивание документов
    if download_docs and all_results:
        docs_dir = Path(__file__).parent.parent / "data" / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nСкачиваю документы в {docs_dir}/ ...")

        for i, contract in enumerate(all_results):
            url = contract.get("url")
            if not url:
                continue

            number = contract.get("number", f"contract_{i}").replace("/", "_").replace(" ", "")
            contract_dir = docs_dir / number
            contract_dir.mkdir(exist_ok=True)

            print(f"  [{i+1}/{len(all_results)}] {contract.get('number','?')}...", end=" ", flush=True)
            docs = fetch_contract_documents(url)
            downloaded = []
            for doc in docs[:5]:  # Не больше 5 файлов на закупку
                path = download_document(doc, contract_dir)
                if path:
                    downloaded.append(str(path))
            contract["documents"] = downloaded
            print(f"{len(downloaded)} файл(ов)")
            time.sleep(0.8)

    saved_to = save_results(all_results, filters)
    print(f"Сохранено -> {saved_to}")
    return all_results


if __name__ == "__main__":
    import sys
    download = "--docs" in sys.argv
    contracts = run(download_docs=download)
