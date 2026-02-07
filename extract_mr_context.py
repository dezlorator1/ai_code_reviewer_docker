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
EXTRACT_CONTEXT_PROMPT = """Ты — первое звено в цепочке анализа Merge Request.

**Твоя роль:** Собрать ГЛОБАЛЬНЫЙ КОНТЕКСТ, который будет использован на следующих этапах:
1. При детальном ревью каждого файла
2. При создании финального отчета для Тимлида

**Проект:** OpenSearch плагин с языком запросов (аналог Splunk)
**Язык:** Java
**Пользователи:** Крупные компании в production

---

GIT DIFF:
```diff
{diff}
```

---

**ТВОЯ ЗАДАЧА:**

Проанализируй diff и создай структурированный контекст. Будь максимально конкретным — указывай имена классов, методов, файлов.

**ВАЖНО:** Следующие этапы будут опираться на твой анализ. Не упусти:
- Breaking changes на уровне архитектуры
- Изменения в Query Language
- Зависимости между файлами

---

**ФОРМАТ ВЫВОДА (строго следуй структуре):**

# 📋 MR Global Context

**Дата анализа:** {timestamp}
**Файлов изменено:** {file_count}

---

## 🎯 ЦЕЛЬ MR

**Что делает этот MR (1-2 предложения):**
[Объясни бизнес-цель. Примеры:
- "Добавление команды percentile() для расчета процентилей в агрегациях"
- "Рефакторинг QueryParser — выделение валидации в отдельный модуль"
- "Исправление бага с NPE в команде stats при null значениях"]

**Тип изменения:**
[Выбери ОДИН: Feature / Bugfix / Refactoring / Performance / Breaking Change]

---

## 📂 ИЗМЕНЕННЫЕ ФАЙЛЫ

**ИНСТРУКЦИЯ:** Для каждого файла укажи ЧТО ИМЕННО изменилось (не просто "изменен", а конкретно).

### Новые файлы
[Если есть:]
- `src/main/PercentileCommand.java` — новая команда для расчета процентилей

### Измененные файлы
[Для КАЖДОГО файла:]
- `src/main/QueryParser.java` — добавлен метод parsePercentile(), изменена логика валидации
- `src/main/StatsCommand.java` — исправлена обработка null, добавлена проверка типов

### Удаленные файлы
[Если есть:]
- `src/deprecated/LegacyParser.java` — удален deprecated код

---

## ⚠️ BREAKING CHANGES (Архитектурный уровень)

**КРИТИЧНО:** Эта секция используется в финальном отчете напрямую!

[Если НЕТ breaking changes:]
Не обнаружено.

[Если ЕСТЬ, распиши подробно:]

### Query Language
- **Удалена команда `timechart`** — deprecated с v2.0, может сломать старые дашборды
- **Изменено поведение `stats count()`** — теперь возвращает 0 вместо null для пустых результатов
- **Изменен приоритет операторов** — AND теперь выше OR (может изменить результаты сложных запросов)

### Публичное API
- **Удален метод `QueryExecutor.executeLegacy()`** — может сломать внешние интеграции
- **Изменена сигнатура `Parser.parse(String query, Context ctx)`** — добавлен обязательный параметр ctx

### Системные настройки
- **Удалена настройка `legacy_mode`** — старые конфиги сломаются
- **Изменен default для `query.timeout`** — с 30s на 60s (влияет на поведение без явного конфига)

---

## 🔧 ИЗМЕНЕНИЯ В QUERY LANGUAGE

**КРИТИЧНО для пользователей:** Детально опиши влияние на запросы.

[Если НЕТ изменений:]
Не обнаружено.

[Если ЕСТЬ:]

### Новые команды
- `percentile(field, p)` — вычисление p-процентиля (например, percentile(response_time, 95))
- `rare(field, limit=10)` — поиск редких значений

### Измененные команды
- `stats avg(field)` — теперь корректно обрабатывает null (раньше падал с NPE)
- `sort field` — добавлена опция `-desc` для обратной сортировки

## ⚙️ Системные настройки

### Изменения в синтаксисе/парсинге
- Изменен приоритет операторов: AND > OR (раньше было одинаково)
- Добавлена поддержка вложенных скобок в агрегациях

**Влияние на пользователей:**
[Конкретно опиши последствия:]
- Запросы с `field1 OR field2 AND field3` изменят результаты → нужно пересчитать дашборды
- Запросы с `stats avg(nullable_field)` перестанут падать → это хорошо

---

## ⚙️ ИЗМЕНЕНИЯ В СИСТЕМНЫХ НАСТРОЙКАХ

[Если НЕТ:]
Не обнаружено.

[Если ЕСТЬ:]
- `query.timeout` — изменен default с 30s на 60s (влияет на production без явного конфига)
- `query.max_depth` — добавлена новая настройка (default: 10)
- `legacy_mode` — удалена (старые конфиги с этой настройкой сломаются)

---

## 🔗 ЗАВИСИМОСТИ МЕЖДУ ФАЙЛАМИ

**ВАЖНО для детального ревью:** Укажи связи, чтобы избежать ложных срабатываний.

[Формат: Файл A → Файл B (что связывает)]

**Связанные изменения в этом MR:**
- `QueryParser.java` добавил метод `parsePercentile()`
  → `PercentileCommand.java` использует этот метод
  → ✓ Оба файла в этом MR — не проблема

- `QueryExecutor.java` изменил сигнатуру `execute(Query q, Context ctx)`
  → `StatsCommand.java` обновил вызов под новую сигнатуру
  → ✓ Оба изменения в этом MR — согласовано

**Потенциальные проблемы:**
[Только если что-то НЕ согласовано:]
- `UserService.getUserById()` теперь возвращает Optional
  → ⚠️ Все места вызова должны быть обновлены (проверить на этапе детального ревью)

---

## 📊 ТЕХНИЧЕСКАЯ СВОДКА

**Масштаб изменений:**
- Новых классов: [N]
- Измененных классов: [N]
- Удаленных классов: [N]

**Затронутые модули:**
- `com.company.query.parser` — парсинг запросов
- `com.company.query.commands` — выполнение команд
- `com.company.aggregation` — агрегации
- `com.company.settings` — системные настройки

---

**ПРАВИЛА:**
1. Будь конкретным — называй классы, методы, настройки
2. Breaking changes описывай ДЕТАЛЬНО — они идут в финальный отчет
3. Указывай влияние на пользователей (не только что изменилось, но и что это значит)
4. Зависимости между файлами — это критично для избежания ложных срабатываний
5. Пиши на русском, четко, структурированно
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