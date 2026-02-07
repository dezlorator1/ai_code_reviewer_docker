#!/usr/bin/env python3
"""
Review individual code chunk from diff.
Supports multi-project MRs with project prefixes.
"""

import argparse
import re
from pathlib import Path
import logging
import requests
from datetime import datetime
import yaml

# Загрузка конфига
config_path = Path(__file__).parent / "config.yml"

with open(config_path) as f:
    config = yaml.safe_load(f)

# ==== LOG CONFIG ====
SCRIPT_NAME = Path(__file__).name
LOG_FILE = Path(config['paths']['LOG_FILE'])
MR_CONTEXT_FILE = Path(config['paths']['OUT_DIR']) / "mr_context.md"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(SCRIPT_NAME)

# ==== CONFIG ====
API_URL = config['llm']['api_url']
MODEL = config['llm']['model']
MAX_TOKENS = config['llm']['max_tokens']

# ==== PROMPT ====
PROMPT_TEMPLATE = """Ты — опытный Java-архитектор и Security эксперт. Твоя задача — провести ревью изменений в конкретном файле для Тимлида.

Тимлид ведет много проектов и может быть не в контексте деталей. Ему нужно четко понимать:
1. Зачем трогали этот файл (связь с глобальной задачей MR).
2. Есть ли риски для продакшена (баги, уязвимости, падение производительности).
3. Есть ли Breaking Changes (особенно в Query Language).

---

### ГЛОБАЛЬНЫЙ КОНТЕКСТ MR (Цель изменений):
{mr_context}

---

### АНАЛИЗИРУЕМЫЙ ФАЙЛ: {filename}

**ОРИГИНАЛ (Состояние до изменений):**
```java
{original}
```

**GIT DIFF (Изменения в этом MR):**
```diff
{diff}
```

---

### ИНСТРУКЦИИ ПО АНАЛИЗУ:

1. **Контекст — это ключ:** Если видишь удаленный метод, проверь ГЛОБАЛЬНЫЙ КОНТЕКСТ. Возможно, он перенесен в другой класс. Если это так — это не ошибка, а рефакторинг.
2. **Игнорируй покрытие тестами:** Не пиши "нет тестов", если только сами тесты не содержат багов.
3. **Бизнес-логика важнее стиля:** Тимлиду не важны отступы. Ему важно, не упадет ли прод.
4. **Query Language:** Если файл относится к парсингу или исполнению запросов — ищи изменения синтаксиса или поведения команд.

---

### ФОРМАТ ОТЧЕТА (Markdown, на русском языке):

### {filename}

**📝 Что сделано:**
[1-2 предложения. Объясни суть изменений в этом файле простым языком. Например: "Добавлена валидация входных данных для команды stats" или "Класс адаптирован под новый интерфейс QueryExecutor".]

**💥 Breaking Changes / Критичные изменения логики:**
[Если есть — опиши жирным. Если нет — напиши "Не обнаружено".]
*Пример:* **Изменена сигнатура публичного метода `execute()`, это сломает кастомные плагины.**

#### 🐛 Найденные проблемы и Риски

[Если проблем нет — напиши "✅ Критических проблем не обнаружено".]
[Если есть, группируй по критичности:]

**🔴 CRITICAL (Блокирует релиз)**
*Баги, приводящие к падению (NPE), потере данных, дыры в безопасности, поломка основной логики, неправильный выбор алгоритмов.*
- **Строка N:** [Суть проблемы]
  - **Влияние:** [Почему это страшно? Например: "Вызовет падение всего узла при пустом запросе"]
  - **Решение:** [Как исправить]

**🟡 HIGH (Важно исправить)**
*Логические ошибки, деградация производительности, нарушение контрактов API, отсутствие обработки ошибок.*
- **Строка N:** ...

**🟢 MEDIUM (Стоит обратить внимание)**
*Код с запашком, запутанная логика, отсутствие валидации (не критичной).*
- **Строка N:** ...

### ⚪ Незначительные замечания (LOW)

#### ℹ️ Заметки по рефакторингу (Internal)
[Здесь кратко перечисли изменения внутренних методов/классов, которые не влияют на внешнее поведение, но полезны для понимания масштаба.]
- Метод `helper()` удален (инлайн).
- Поле `logger` переименовано в `log`.
- Добавлен новый вспомогательный класс `Utils`.

---

ПРАВИЛА:
1. Будь предельно конкретен. Указывай номера строк.
2. Не выдумывай проблемы. Если код выглядит нормально — так и пиши.
3. Различай "Оригинал" (было) и "Diff" (стало). Не ругайся на код, который был удален.
4. Отвечай на русском языке
"""

# ==== FUNCTIONS ====
def load_mr_context():
    """Load MR global context if available."""
    if MR_CONTEXT_FILE.exists():
        context = MR_CONTEXT_FILE.read_text(errors="ignore")
        log.info(f"MR_CONTEXT LOADED size={len(context)} bytes")
        return context
    else:
        log.warning(f"MR_CONTEXT FILE NOT FOUND: {MR_CONTEXT_FILE}")
        return "MR context not available - reviewing file in isolation."

def extract_file_from_diff(diff_text):
    """Extract file path from diff (with project prefix if present)."""
    m = re.search(r"diff --git a/(.*?) b/", diff_text)
    return m.group(1) if m else None

def load_original(project_roots, file_path):
    """
    Load original file, supporting multi-project structure.

    Args:
        project_roots: String with paths separated by ':' (e.g. "/p1:/p2")
        file_path: File path with or without project prefix (e.g. "backend/src/Api.java")

    Returns:
        File content or error message
    """
    log.info(f"Loading original file: {file_path}")
    log.info(f"Project roots: {project_roots}")

    # Split multiple project paths
    project_paths = project_roots.split(':')

    # Check if path has project prefix (e.g. "backend/src/File.java")
    parts = file_path.split('/', 1)

    if len(parts) == 2 and len(project_paths) > 1:
        # Multi-project mode: file_path = "backend/src/Api.java"
        project_prefix = parts[0]  # "backend"
        relative_path = parts[1]   # "src/Api.java"

        log.info(f"Multi-project mode: prefix={project_prefix}, relative={relative_path}")

        # Try to find matching project
        for project_path in project_paths:
            project_name = Path(project_path).name

            if project_name == project_prefix:
                full_path = Path(project_path) / relative_path
                log.info(f"Trying: {full_path}")

                if full_path.exists():
                    log.info(f"FOUND: {full_path}")
                    return full_path.read_text(errors="ignore")

        log.warning(f"ORIGINAL FILE NOT FOUND for prefix '{project_prefix}': {file_path}")
        return f"<FILE NOT FOUND: {file_path}>"

    else:
        # Single project mode: try each project root
        for project_path in project_paths:
            relative_path = parts[1]
            #log.info(f"Project path: {project_path}. File path: {relative_path}")
            full_path = Path(project_path) / relative_path
            log.info(f"Trying: {full_path}")

            if full_path.exists():
                log.info(f"FOUND: {full_path}")
                return full_path.read_text(errors="ignore")

        log.warning(f"ORIGINAL FILE NOT FOUND: {file_path}")
        return f"<FILE NOT FOUND: {file_path}>"

def call_llm(prompt):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a strict code reviewer for OpenSearch plugin with query language expertise."},
            {"role": "user", "content": prompt}
        ],
        "temperature": config['llm']['temperature'],
        "max_tokens": MAX_TOKENS
    }

    log.info("LLM REQUEST START")
    start = datetime.now()

    r = requests.post(API_URL, json=payload, timeout=300)
    r.raise_for_status()

    dt = (datetime.now() - start).total_seconds()
    log.info(f"LLM REQUEST FINISH time={dt}s")

    return r.json()["choices"][0]["message"]["content"]

# ==== MAIN ====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", required=True, help="Path to diff chunk file")
    ap.add_argument("--projects", required=True, help="Project roots separated by ':' (e.g. /p1:/p2)")
    ap.add_argument("--out", required=True, help="Output file for review")
    args = ap.parse_args()

    log.info(f"START chunk={args.chunk}")
    log.info(f"Projects: {args.projects}")

    # Load MR global context
    mr_context = load_mr_context()

    diff_text = Path(args.chunk).read_text()
    file_path = extract_file_from_diff(diff_text)
    log.info(f"DIFF FILE PARSED target_file={file_path}")

    original = ""
    if file_path:
        original = load_original(args.projects, file_path)
        log.info(f"ORIGINAL SIZE bytes={len(original)}")

    # Smart truncation for large files
    MAX_ORIGINAL_SIZE = 50000
    if len(original) > MAX_ORIGINAL_SIZE:
        log.warning(f"ORIGINAL FILE TOO LARGE ({len(original)} bytes), TRUNCATING")
        imports_section = original[:5000]
        relevant_code = original[-(MAX_ORIGINAL_SIZE - 5000):]
        original = imports_section + "\n\n[... middle section truncated ...]\n\n" + relevant_code
        log.info(f"TRUNCATED TO {len(original)} bytes (kept imports + tail)")

    prompt = PROMPT_TEMPLATE.format(
        filename=file_path,
        original=original,
        diff=diff_text,
        mr_context=mr_context
    )
    log.info(f"PROMPT SIZE chars={len(prompt)}")

    result = call_llm(prompt)

    Path(args.out).write_text(result)

    log.info(f"WRITE RESULT {args.out} bytes={len(result)}")
    log.info(f"END chunk={args.chunk}")

if __name__ == "__main__":
    main()