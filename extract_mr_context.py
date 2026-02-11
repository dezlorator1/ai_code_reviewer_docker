#!/usr/bin/env python3
"""
Extract global context from git diff for MR review.
Analyzes entire diff and creates context file with:
- All modified files
- Types of changes
- Affected components
- Potential breaking changes
"""

import argparse
import logging
import re
from pathlib import Path
from datetime import datetime
import requests
import yaml


# === Load config ===
config_path = Path(__file__).parent / "config.yml"
with open(config_path) as f:
    config = yaml.safe_load(f)

# === Paths ===
MR_CONTEXT_FILE = Path(config['paths']['OUT_DIR']) / "mr_context.md"
LOG_FILE = Path(config['paths']['LOG_FILE'])

# === LLM Settings ===
API_URL = config['llm']['api_url']
MODEL = config['llm']['model']
MAX_TOKENS = config['llm']['max_tokens']
TEMPERATURE = config['llm']['temperature']

# === Logging ===
SCRIPT_NAME = Path(__file__).name
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


# === Prompt ===
EXTRACT_CONTEXT_PROMPT = """Ты — аналитик кода, собирающий контекст для code review.

**Проект:** OpenSearch плагин с языком запросов (аналог Splunk), Java

**Твоя задача:** Создать глобальный контекст MR для последующих этапов анализа.

**ВАЖНО:** Фокусируйся на РЕАЛЬНЫХ breaking changes и качестве кода, не на формальностях.

---

GIT DIFF:
```diff
{diff}
```

---

**ФОРМАТ ВЫВОДА (пиши ТОЛЬКО на русском языке):**

# 📋 MR Global Context

**Дата анализа:** {timestamp}
**Файлов изменено:** {file_count}

---

## 🎯 ЦЕЛЬ MR

**Что делает этот MR:**
[Объясни бизнес-цель в 1-2 предложениях]

**Тип изменения:**
[Feature / Bugfix / Refactoring / Performance]

---

## 📂 ИЗМЕНЕННЫЕ ФАЙЛЫ

### Новые файлы
[Если есть:]
- `src/main/Class.java` — [что делает]

### Измененные файлы
[Для КАЖДОГО:]
- `src/main/Class.java` — [что конкретно изменилось]

### Удаленные файлы
[Если есть:]
- `src/old/Class.java` — [что удалили]

---

## ⚠️ BREAKING CHANGES

**ПРАВИЛА КЛАССИФИКАЦИИ:**

**BREAKING CHANGE:**
- Изменение поведения Query Language команд (stats, eval, где, и т.д.)
- Изменения в файлах *RestActions.java (это эндпоинты API)
- Новые настройки которые меняют дефолтное поведение

**НЕ BREAKING:**
- Удаление приватных/internal методов
- Новые поля в JSON (можно игнорировать)
- Рефакторинги
- Переименования

---

[Если НЕТ breaking changes:]
Не обнаружено.

[Если ЕСТЬ:]

### Query Language
- **Изменено поведение команды `stats count()`** — теперь возвращает 0 вместо null
  → Дашборды с проверкой `if (result == null)` могут сломаться

### Эндпоинты (*RestActions.java)
[Только если изменены файлы *RestActions.java:]
- **Изменена сигнатура метода в QueryRestActions** — добавлен обязательный параметр `timeout`
  → Внешние вызовы без параметра сломаются

### Системные настройки (влияют на поведение)
- **Добавлена настройка `strict_mode`** — при включении меняет парсинг запросов
  → Корректные запросы могут начать падать
- **Изменен default `query.timeout`** — с 30s на 60s
  → Поведение без явного конфига изменится

---

## 🔧 ИЗМЕНЕНИЯ В QUERY LANGUAGE

[Если НЕТ:]
Не обнаружено.

[Если ЕСТЬ:]

### Новые команды
- `percentile(field, p)` — расчет процентилей

### Изменения в поведении команд
- `stats avg()` — теперь корректно обрабатывает null (раньше падал)
- `eval` — изменен приоритет операторов AND/OR

### Изменения в парсинге
- Добавлена поддержка вложенных скобок в агрегациях
- Изменена обработка escape-последовательностей

**Влияние:**
[Что изменится для пользователей]

---

## ⚙️ СИСТЕМНЫЕ НАСТРОЙКИ

[Фокус на настройках которые МЕНЯЮТ ПОВЕДЕНИЕ]

### Новые настройки
- `strict_mode` (default: false) — при включении меняет парсинг
- `max_depth` (default: 10) — ограничивает глубину вложенности

### Изменения дефолтов
- `query.timeout`: 30s → 60s (влияет на поведение без явного конфига)

**Потенциальное влияние:**
- При включении `strict_mode` могут упасть корректные запросы
- Увеличение timeout может изменить поведение long-running запросов

---

## 🔗 ЗАВИСИМОСТИ МЕЖДУ ФАЙЛАМИ

**КРИТИЧНО для избежания ложных срабатываний!**

**Связанные изменения в этом MR:**
- `Parser.java` добавил метод `parsePercentile()`
  → `PercentileCommand.java` использует этот метод
  → ✓ Оба в MR — не проблема

- `Graph.java` изменил сигнатуру `fillNodes()`
  → `GraphService.java` обновил вызов
  → ✓ Согласовано в этом MR

**Потенциальные проблемы:**
[Только если что-то НЕ согласовано:]
- `Service.getUser()` изменил возвращаемый тип на Optional
  → ⚠️ Проверить все вызовы в других файлах

---

## 📊 ТЕХНИЧЕСКАЯ СВОДКА

**Масштаб:**
- Новых классов: [N]
- Izmененных классов: [N]
- Удаленных классов: [N]

**Затронутые модули:**
- `com.company.query` — [что изменилось]
- `com.company.service` — [что изменилось]

**Рефакторинги:**
[Если были значимые:]
- Переименование метода `getMaxDeep` → `getLevels`
- Выделение валидации в отдельный класс

---

**ПРАВИЛА:**
1. Пиши ТОЛЬКО на русском языке
2. Будь конкретным — называй классы, методы
3. Breaking changes — только реальные (Query Language, *RestActions.java, настройки меняющие поведение)
4. Зависимости файлов — критично для следующих этапов
5. Фокус на изменениях ПОВЕДЕНИЯ, не на удалениях
"""



# === Functions ===

def extract_changed_files(diff_text):
    """Extract list of changed files from diff."""
    files = []
    for match in re.finditer(r'^diff --git a/(.*?) b/', diff_text, re.MULTILINE):
        files.append(match.group(1))
    return files


def call_llm(prompt):
    """Call LLM API and return response."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a technical architect analyzing code changes."},
            {"role": "user", "content": prompt}
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS
    }

    log.info("MR_CONTEXT LLM REQUEST START")
    start = datetime.now()

    try:
        r = requests.post(API_URL, json=payload, timeout=600)
        r.raise_for_status()
    except Exception as e:
        log.error(f"LLM REQUEST FAILED: {e}")
        raise

    dt = (datetime.now() - start).total_seconds()
    log.info(f"MR_CONTEXT LLM REQUEST FINISH time={dt}s status={r.status_code}")

    return r.json()["choices"][0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser(description="Extract MR context from git diff")
    parser.add_argument("--diff", required=True, help="Path to diff file")
    args = parser.parse_args()

    log.info(f"MR_CONTEXT EXTRACTION START diff={args.diff}")

    # Read diff
    diff_path = Path(args.diff)
    if not diff_path.exists():
        log.error(f"DIFF FILE NOT FOUND: {diff_path}")
        return

    diff_text = diff_path.read_text(errors="ignore")
    log.info(f"DIFF LOADED size={len(diff_text)} bytes")

    # Quick analysis
    changed_files = extract_changed_files(diff_text)
    file_count = len(changed_files)
    log.info(f"FILES CHANGED: {file_count}")
    log.info(f"FILES: {', '.join(changed_files[:5])}{'...' if file_count > 5 else ''}")

    # Truncate if too large
    MAX_DIFF_CHARS = 60_000  # ~80k tokens upper bound
    if len(diff_text) > MAX_DIFF_CHARS:
        log.warning(f"DIFF TOO LARGE ({len(diff_text)} chars), TRUNCATING to {MAX_DIFF_CHARS}")
        diff_text = diff_text[:MAX_DIFF_CHARS]

    # Build prompt
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = EXTRACT_CONTEXT_PROMPT.format(
        diff=diff_text,
        timestamp=timestamp,
        file_count=file_count
    )

    log.info(f"PROMPT SIZE chars={len(prompt)}")

    # Call LLM
    context = call_llm(prompt)

    # Save result
    MR_CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    MR_CONTEXT_FILE.write_text(context)

    log.info(f"MR_CONTEXT WRITTEN to {MR_CONTEXT_FILE} bytes={len(context)}")
    log.info("MR_CONTEXT EXTRACTION END")

    # Print summary
    print(f"\n{'='*60}")
    print(f"MR Context extracted successfully!")
    print(f"Output: {MR_CONTEXT_FILE}")
    print(f"Files analyzed: {file_count}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()