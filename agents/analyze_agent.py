"""
Агент анализа документов через Claude CLI.
Универсальный — принимает любые файлы и любой промпт.

CLI:
    python agents/analyze_agent.py doc1.pdf doc2.docx
    python agents/analyze_agent.py doc1.pdf --prompt "Проанализируй ТЗ..."
    python agents/analyze_agent.py doc1.pdf --prompt-file prompts/my_prompt.txt
    python agents/analyze_agent.py doc1.pdf --max-chars 30000

Import:
    from agents.analyze_agent import run
    result = run(docs=["path/to/file.pdf"], prompt="Проанализируй...")
"""

import sys
import argparse
import subprocess
import shutil
import platform
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_PROMPT = (
    "Проанализируй документы и дай структурированный ответ по содержанию.\n\n"
    "---\n\nДОКУМЕНТЫ:\n{documents_text}"
)

PRIORITY_NAMES = ["техническое задание", "тз", "описание объекта", "объект закупки", "требования"]

MAX_CHARS = 40_000


def extract_text(path: Path) -> str:
    """Извлекает текст из PDF, DOCX, DOC, RTF, TXT."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".doc":
        return _extract_doc_legacy(path)
    if ext == ".rtf":
        return _extract_rtf(path)
    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    return f"[Формат {ext} не поддерживается]"


def _extract_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages[:15])
    except ImportError:
        return f"[pdfplumber не установлен: {path.name}]"
    except Exception as e:
        return f"[Ошибка чтения {path.name}: {e}]"


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        return f"[python-docx не установлен: {path.name}]"
    except Exception as e:
        return f"[Ошибка чтения {path.name}: {e}]"


def _extract_doc_legacy(path: Path) -> str:
    """Читает старый бинарный .doc через antiword, с fallback на DOCX (если файл — OOXML)."""
    antiword = shutil.which("antiword")
    if antiword:
        try:
            result = subprocess.run(
                [antiword, "-t", "-w", "0", str(path.absolute())],
                capture_output=True,
                timeout=30,
            )
            text = result.stdout.decode("utf-8", errors="replace").strip()
            if text:
                return text
        except Exception:
            pass

    # Файл может быть OOXML (переименованный .docx) — пробуем python-docx
    import zipfile
    if zipfile.is_zipfile(str(path)):
        return _extract_docx(path)

    if antiword:
        return f"[Не удалось прочитать {path.name}]"
    return f"[antiword не найден, файл не ZIP: {path.name}]"


def _extract_rtf(path: Path) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
        raw = path.read_bytes()
        for enc in ("utf-8", "cp1251", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            content = raw.decode("latin-1")
        return rtf_to_text(content).strip()
    except ImportError:
        return f"[striprtf не установлен: {path.name}]"
    except Exception as e:
        return f"[Ошибка чтения {path.name}: {e}]"


def sort_by_priority(files: list[Path]) -> list[Path]:
    """Файлы с ТЗ и описанием объекта — в начало."""
    def priority(p: Path) -> int:
        name = p.name.lower()
        for i, kw in enumerate(PRIORITY_NAMES):
            if kw in name:
                return i
        return len(PRIORITY_NAMES)
    return sorted(files, key=priority)


def build_documents_text(docs: list[Path | str], max_chars: int = MAX_CHARS) -> str:
    """Собирает текст из списка файлов с учётом лимита символов."""
    files = sort_by_priority([Path(d) for d in docs])
    parts, total = [], 0
    for f in files:
        if not f.exists():
            parts.append(f"[Файл не найден: {f}]")
            continue
        text = extract_text(f)
        if not text.strip():
            continue
        if total + len(text) > max_chars:
            parts.append("[...остальные файлы пропущены из-за лимита объёма]")
            break
        parts.append(f"=== {f.name} ===\n{text}")
        total += len(text)
    return "\n\n".join(parts) if parts else "Документы недоступны."


def run(
    docs: list[Path | str],
    prompt: str = DEFAULT_PROMPT,
    max_chars: int = MAX_CHARS,
    timeout: int = 120,
) -> str:
    """
    Анализирует документы через Claude CLI.

    docs      — список путей к файлам (PDF, DOCX, TXT)
    prompt    — промпт с плейсхолдером {documents_text}
    max_chars — лимит символов суммарного текста документов
    timeout   — таймаут запуска Claude в секундах

    Возвращает текст анализа от Claude.
    """
    docs_text = build_documents_text(docs, max_chars)

    if "{documents_text}" in prompt:
        full_prompt = prompt.replace("{documents_text}", docs_text)
    else:
        full_prompt = f"{prompt}\n\n---\n\nДОКУМЕНТЫ:\n{docs_text}"

    return _run_claude(full_prompt, timeout)


def _run_claude(prompt: str, timeout: int = 120) -> str:
    claude_path = shutil.which("claude.cmd") or shutil.which("claude")
    if not claude_path:
        return "[claude CLI не найден в PATH]"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as tmp:
        tmp.write(prompt)
        tmp_path = tmp.name

    try:
        if platform.system() == "Windows":
            cmd = ["cmd", "/c", claude_path, "--print", f"@{tmp_path}"]
        else:
            cmd = [claude_path, "--print", f"@{tmp_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        return result.stdout.strip() or result.stderr.strip() or "[Нет ответа от Claude]"
    except subprocess.TimeoutExpired:
        return f"[Таймаут анализа ({timeout} сек)]"
    except Exception as e:
        return f"[Ошибка запуска Claude: {e}]"
    finally:
        os.unlink(tmp_path)


def main():
    parser = argparse.ArgumentParser(description="Агент анализа документов через Claude")
    parser.add_argument("docs", nargs="+", help="Пути к файлам для анализа")
    parser.add_argument("--prompt", help="Промпт для анализа (текст)")
    parser.add_argument("--prompt-file", help="Путь к файлу с промптом")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS, help="Лимит символов документов")
    parser.add_argument("--timeout", type=int, default=120, help="Таймаут Claude в секундах")
    args = parser.parse_args()

    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    else:
        prompt = DEFAULT_PROMPT

    result = run(docs=args.docs, prompt=prompt, max_chars=args.max_chars, timeout=args.timeout)
    print(result)


if __name__ == "__main__":
    main()
