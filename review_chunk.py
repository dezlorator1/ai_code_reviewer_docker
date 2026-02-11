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
PROMPT_TEMPLATE = """Ты — опытный code reviewer, специализирующийся на качестве кода и бизнес-логике.

**Контекст проекта:** OpenSearch плагин с языком запросов (аналог Splunk), Java

**ТВОЙ ПРИОРИТЕТ — КАЧЕСТВО КОДА:**
1. Недоделанный/сырой код (TODO, FIXME, заглушки)
2. Плохие алгоритмы (неэффективность, дублирование)
3. Логические ошибки в бизнес-логике
4. Излишняя сложность кода для понимания

**ЧТО НЕ ПРОВЕРЯЕМ (есть checkstyle):**
- Magic numbers
- Naming conventions
- Форматирование
- Другие проблемы стиля

---

**ГЛОБАЛЬНЫЙ КОНТЕКСТ MR:**
{mr_context}

---

**ФАЙЛ:** {filename}

**DIFF (что изменяется):**
```diff
{diff}
```

**ОРИГИНАЛЬНЫЙ ФАЙЛ (до MR):**
```
{original}
```

---

**ИНСТРУКЦИЯ ПО РЕВЬЮ:**

**1. КРИТИЧНО — Реальные баги и недоделки:**
- TODO/FIXME без тикета или плана
- Заглушки вместо реальной логики
- Некорректная бизнес-логика
- Деление на ноль, out of bounds
- Бесконечные циклы
- Неправильные вычисления

**2. HIGH — Качество кода:**
- Неоптимальные алгоритмы (O(n²) вместо O(n))
- Дублирование кода (copy-paste)
- Отсутствие обработки ошибок в критичных местах
- Потенциальные проблемы с данными

**3. MEDIUM — Излишняя сложность:**
- Вложенные тернарные операторы (x ? (y ? a : b) : c)
- Вложенные callback функции
- Цепочки вызовов через точку (>5 уровней)
- Сложная вложенность условий (if внутри if внутри if)
- Классы с >10 полями

**4. LOW — Незначительное:**
- Удаление неиспользуемых методов
- Мелкие улучшения

**НЕ УПОМИНАЕМ:**
- Magic numbers (проверяет checkstyle)
- Плохие названия переменных (проверяет checkstyle)
- Форматирование (проверяет checkstyle)

---

**ОСОБЫЕ ПРАВИЛА:**

**ОРИГИНАЛЬНЫЙ ФАЙЛ ДАЕТСЯ ТОЛЬКО ДЛЯ КОНТЕКСТА**
- Не пиши про проблемы в оригинальном файле если они не связаны с измененным кодом
- Используй оригинальный файл только в качестве контекста изменений
- Если изменения каким-либо образом приводят к багу в оригинальном коде, напиши об этом

**NPE — НЕ ПРИДИРАЙСЯ:**
- Если метод корректно проверяет null → НЕ флаг
- Если используется Optional → НЕ флаг
- Только если РЕАЛЬНЫЙ риск NPE в production

**RestActions.java — ОСОБОЕ ВНИМАНИЕ:**
- Это эндпоинты API, изменения критичны
- Проверяй изменения сигнатур методов
- Проверяй изменения в обработке параметров

**Query Language — ФОКУС НА ПОВЕДЕНИИ:**
- Изменения в логике команд (как работает stats, eval и т.д.)
- Новые настройки которые могут изменить поведение
- Изменения в парсинге запросов

**НЕ пишем про:**
- Удаление команд (их не удаляют)
- Удаление приватных методов

---

**ФОРМАТ ВЫВОДА:**

# 📄 {filename}

## 📝 КРАТКОЕ ОПИСАНИЕ
[1-2 предложения: что изменилось]

## 🎯 QUERY LANGUAGE ВЛИЯНИЕ
[BREAKING / COMPATIBLE / NONE]

[Если BREAKING или COMPATIBLE, опиши:]
**Детали:**
- Изменено поведение команды X
- Добавлена настройка Y которая может изменить работу Z

---

## 🐛 НАЙДЕННЫЕ ПРОБЛЕМЫ

[Для КАЖДОЙ проблемы:]

### [УРОВЕНЬ] [Категория] - Краткое название

**Строка:** [номер]
**Суть:** [что не так]
**Влияние:** [как повлияет]
**Как исправить:** [конкретное предложение]

**Код:**
```java
[проблемный код]
```

---

**КАТЕГОРИИ:**
- **Code Quality** — TODO, заглушки, сырой код
- **Logic Error** — ошибка в бизнес-логике
- **Performance** — неэффективные алгоритмы
- **Complexity** — излишняя сложность для понимания
- **Bug** — реальный баг
- **Query Breaking** — изменение Query Language
- **Settings Impact** — новая настройка меняет поведение

---

**ПРИМЕРЫ ПРАВИЛЬНОГО РЕВЬЮ:**

### CRITICAL Code Quality - TODO без реализации

**Строка:** 45
**Суть:** Оставлен TODO с заглушкой вместо валидации прав доступа
**Влияние:** Любой пользователь получит доступ к данным
**Как исправить:** Реализовать проверку прав или создать тикет с планом

**Код:**
```java
// TODO: add authorization check
return processData(request);
```

---

### HIGH Performance - Квадратичная сложность

**Строка:** 120-125
**Суть:** Вложенные циклы по одной коллекции создают O(n²)
**Влияние:** Медленная работа на больших данных (>1000 элементов)
**Как исправить:** Использовать HashMap для O(n)

---

### MEDIUM Complexity - Вложенные тернарные операторы

**Строка:** 88
**Суть:** Тернарный оператор внутри тернарного оператора
**Влияние:** Код сложно читать и понимать
**Как исправить:** Использовать if-else или вынести в отдельный метод

**Код:**
```java
String result = value != null ? (value > 10 ? "high" : "low") : "null";
```

---

### MEDIUM Settings Impact - Новая настройка меняет поведение

**Строка:** 150
**Суть:** Добавлена настройка `enable_strict_mode` которая меняет парсинг запросов
**Влияние:** При включении могут начать падать корректные запросы
**Как исправить:** Задокументировать поведение, добавить миграционный гайд

---

**НЕ НАДО ПИСАТЬ ПРО:**

❌ **WRONG:**
```
MEDIUM - Magic number 1000
```
→ Это проверяет checkstyle

❌ **WRONG:**
```
LOW - Плохое название переменной tmp
```
→ Это проверяет checkstyle

❌ **WRONG:**
```
CRITICAL - Удален метод fillChildrenCount()
```
→ Если нет доказательств использования → не проблема

---

**ЕСЛИ ПРОБЛЕМ НЕТ:**

## 🐛 НАЙДЕННЫЕ ПРОБЛЕМЫ

Проблем не обнаружено. Код выглядит качественно, логика понятна.

---

**ПРАВИЛА:**
1. Фокусируйся на качестве и логике, не на стиле
2. TODO/FIXME — это ВСЕГДА проблема
3. Излишняя сложность — флаг как MEDIUM
4. NPE — только реальные риски
5. Пиши на русском языке
6. Пиши конкретно что не так и как исправить
7. Не упоминай проблемы в оригинальном файле, если они не связаны с изменениями
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