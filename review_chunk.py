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
PROMPT_TEMPLATE = """Ты — второе звено в цепочке анализа Merge Request.

**Твоя роль:** Детально проанализировать ОДИН файл и найти ВСЕ проблемы.

**Важно:** Твой вывод будет агрегирован на следующем этапе в финальный отчет для Тимлида.
Поэтому записывай информацию СТРУКТУРИРОВАННО и ПОЛНО.

---

**ГЛОБАЛЬНЫЙ КОНТЕКСТ MR:**
{mr_context}

---

**ФАЙЛ НА РЕВЬЮ:** {filename}

**GIT DIFF (что изменяется в этом файле):**
```diff
{diff}
```

**ОРИГИНАЛЬНЫЙ ФАЙЛ (состояние ДО этого MR):**
```
{original}
```

---

**ТВОЯ ЗАДАЧА:**

1. Проанализируй изменения в файле
2. Найди ВСЕ баги и проблемы по уровням (CRITICAL/HIGH/MEDIUM/LOW)
3. Определи влияние на Query Language (если файл связан с query/parser/command)
4. Запиши всё структурированно для последующей агрегации

**КРИТИЧНО:**
- Используй информацию из "ЗАВИСИМОСТИ МЕЖДУ ФАЙЛАМИ" чтобы не ругаться на то, что добавлено в других файлах этого же MR
- Различай ORIGINAL FILE (до MR) и DIFF (изменения MR):
  * Если поле есть только в DIFF с `+` → это новое добавление (НЕ дубликат)
  * Если поле есть и в ORIGINAL и в DIFF с `+` → это дубликат (проблема)

---

**ФОРМАТ ВЫВОДА:**

# 📄 {filename}

## 📝 КРАТКОЕ ОПИСАНИЕ
[1-2 предложения: что изменилось в файле]

## 🎯 QUERY LANGUAGE ВЛИЯНИЕ
[Выбери ОДИН вариант:]
- **BREAKING** — изменения ломают существующие запросы
- **COMPATIBLE** — изменения обратно совместимы
- **NONE** — файл не связан с Query Language

[Если BREAKING или COMPATIBLE, опиши:]
**Детали:**
- Изменено поведение команды X
- Добавлена новая команда Y

---

## 🐛 НАЙДЕННЫЕ ПРОБЛЕМЫ

**ИНСТРУКЦИЯ ПО ЗАПИСИ ПРОБЛЕМ:**

Для КАЖДОЙ проблемы используй формат:

### [УРОВЕНЬ] [Категория] - Краткое название

**Файл:** [название файла]
**Строка:** [номер строки или диапазон]
**Суть:** [что не так]
**Влияние:** [как это повлияет на production/пользователей]
**Как исправить:** [конкретное предложение]

**Код:**
```java
[проблемный код из diff]
```

---

**УРОВНИ:**
- **CRITICAL** — NPE, потеря данных, security уязвимости, race conditions, breaking changes не задокументированные
- **HIGH** — логические ошибки, неправильные алгоритмы, проблемы производительности >20%
- **MEDIUM** — отсутствие валидации, code smells, неоптимальные решения
- **LOW** — стиль кода, мелкие улучшения

**КАТЕГОРИИ:**
- Bug — явный баг
- Security — уязвимость безопасности
- Performance — проблема производительности
- Logic — ошибка в бизнес-логике
- API Breaking — изменение публичного API
- Query Breaking — изменение Query Language
- Validation — отсутствие проверок
- Style — стилистика кода

---

**ПРИМЕРЫ:**

### CRITICAL Bug - NPE при null аргументе

**Строка:** 45
**Суть:** Метод не проверяет null перед вызовом .toString()
**Влияние:** Production упадет с NPE при первом же null значении
**Как исправить:** Добавить проверку `if (value == null) return "null";`

**Код:**
```java
return value.toString(); // NPE если value == null
```

---

### HIGH Query Breaking - Изменено поведение команды

**Строка:** 120-125
**Суть:** Команда `stats count()` теперь возвращает 0 вместо null
**Влияние:** Дашборды с проверкой `if (result == null)` сломаются
**Как исправить:** Задокументировать breaking change, добавить миграционный гайд

---

### MEDIUM Validation - Отсутствует проверка диапазона

**Строка:** 88
**Суть:** Параметр `limit` не проверяется на допустимые значения
**Влияние:** Пользователь может передать limit=-100 или limit=999999999
**Как исправить:** Добавить `if (limit < 1 || limit > 1000) throw new IllegalArgumentException(...)`

---

**ОСОБЫЕ ПРОВЕРКИ ДЛЯ QUERY LANGUAGE ФАЙЛОВ:**

Если файл в пакетах: query, parser, executor, aggregation, command — обращай ОСОБОЕ внимание на:
- Изменения приоритета операторов
- Изменения в парсинге команд
- Изменения в вычислениях агрегаций
- Удаление/изменение поддержки синтаксиса

---

**ЕСЛИ ПРОБЛЕМ НЕТ:**

## 🐛 НАЙДЕННЫЕ ПРОБЛЕМЫ

Проблем не обнаружено. Изменения выглядят безопасно.

[Опционально можешь добавить позитивный комментарий о качестве кода]

---

**ПРАВИЛА:**
1. Будь дотошным — лучше ложное срабатывание, чем пропущенный баг
2. Используй контекст из "ЗАВИСИМОСТИ" — не ругайся на то, что добавлено в других файлах MR
3. Пиши на русском, структурированно
4. Каждую проблему оформляй в одинаковом формате (для агрегации)
5. Указывай конкретные строки кода
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