"""
Анализатор ТЗ закупок.
Читает документы из data/documents/, извлекает текст и запускает claude для анализа.
Вызов: python agents/analyze_tz.py [папка_с_документами]
"""

import sys
import json
import os
from pathlib import Path

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


ANALYSIS_PROMPT = """Ты — эксперт по государственным закупкам (44-ФЗ). Проанализируй документы закупки и дай структурированный ответ:

1. **Предмет контракта** — что именно требуется (1-2 предложения)
2. **Ключевые требования** — технические, квалификационные, опыт, лицензии
3. **Риски и сложности** — что может быть проблемой для участника
4. **Оценка реалистичности НМЦ** — завышена, занижена или нормальная
5. **Рекомендация** — стоит ли участвовать (да/нет/требует изучения) и почему

---

ДОКУМЕНТЫ ЗАКУПКИ:

{documents_text}
"""

PRIORITY_NAMES = ["описание объекта", "техническое задание", "тз", "объект закупки", "требования"]


def extract_text_docx(path: Path) -> str:
    if not HAS_DOCX:
        return f"[python-docx не установлен, файл: {path.name}]"
    try:
        doc = DocxDocument(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        return f"[Ошибка чтения {path.name}: {e}]"


def extract_text_pdf(path: Path) -> str:
    if not HAS_PDF:
        return f"[pdfplumber не установлен, файл: {path.name}]"
    try:
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages[:15])
    except Exception as e:
        return f"[Ошибка чтения {path.name}: {e}]"


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".docx",):
        return extract_text_docx(path)
    if ext in (".doc",):
        # .doc (старый формат) — пробуем через docx как fallback
        return extract_text_docx(path)
    if ext == ".pdf":
        return extract_text_pdf(path)
    return f"[Формат {ext} не поддерживается]"


def sort_by_priority(files: list[Path]) -> list[Path]:
    """ТЗ и описание объекта — в начало."""
    def priority(p: Path) -> int:
        name_lower = p.name.lower()
        for i, keyword in enumerate(PRIORITY_NAMES):
            if keyword in name_lower:
                return i
        return len(PRIORITY_NAMES)
    return sorted(files, key=priority)


def analyze_contract_dir(contract_dir: Path) -> str:
    """Анализирует один каталог с документами закупки через Groq API."""
    files = sort_by_priority(list(contract_dir.glob("*.*")))
    if not files:
        return "Нет документов для анализа."

    parts = []
    total_chars = 0
    for f in files:
        if total_chars > 40_000:
            parts.append(f"\n[...остальные файлы пропущены из-за лимита объёма]")
            break
        text = extract_text(f)
        if text.strip():
            parts.append(f"=== {f.name} ===\n{text}")
            total_chars += len(text)

    if not parts:
        return "Не удалось извлечь текст из документов."

    full_text = "\n\n".join(parts)
    prompt = ANALYSIS_PROMPT.format(documents_text=full_text)

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return "[GROQ_API_KEY не задан в переменных окружения]"

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=120,
        )
        return response.choices[0].message.content or "Нет ответа от Groq."
    except Exception as e:
        return f"[Ошибка Groq API: {e}]"


def run(docs_root: str = "data/documents") -> None:
    root = Path(docs_root)
    if not root.exists():
        print(f"Папка {root} не найдена.")
        return

    contract_dirs = [d for d in sorted(root.iterdir()) if d.is_dir()]
    if not contract_dirs:
        print("Нет папок с документами.")
        return

    print(f"Найдено закупок с документами: {len(contract_dirs)}\n")
    results = []

    for i, cdir in enumerate(contract_dirs):
        print(f"[{i+1}/{len(contract_dirs)}] Анализирую: {cdir.name}")
        analysis = analyze_contract_dir(cdir)
        print(analysis)
        print("\n" + "="*60 + "\n")
        results.append({"contract": cdir.name, "analysis": analysis})

    # Сохраняем результаты
    out = Path("data/analysis_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Результаты сохранены -> {out}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/documents"
    run(target)
