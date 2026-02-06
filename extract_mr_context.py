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
EXTRACT_CONTEXT_PROMPT = """Ты помощник тимлида, который анализирует Merge Request в OpenSearch плагине.

**Контекст проекта:**
- Плагин предоставляет язык запросов (аналог Splunk) для OpenSearch
- Язык: Java
- Используется крупными компаниями в продакшене

**Твоя задача:** Помочь тимлиду быстро понять:
1. Что сделано в этом MR и зачем
2. Какие компоненты затронуты
3. Есть ли критичные изменения (особенно в Query Language)

GIT DIFF:
```diff
{diff}
```

---

ФОРМАТ ВЫВОДА:

# Контекст MR

**Дата анализа:** {timestamp}
**Файлов изменено:** {file_count}

---

## 📋 Что сделано и зачем

[2-4 предложения. Объясни тимлиду цель этого MR:]
- Что добавили/изменили/удалили?
- Какую проблему это решает?
- Это новая фича, рефакторинг, баг-фикс, или что-то другое?

**Примеры:**
- "Добавлена новая команда `percentile()` для вычисления процентилей в агрегациях. Пользователи давно просили эту фичу для статистического анализа."
- "Рефакторинг парсера запросов — вынесена логика валидации в отдельный класс. Улучшает читаемость и тестируемость."
- "Исправлен баг с некорректной обработкой null значений в команде `stats`. Могло приводить к NPE в продакшене."

---

## 📂 Измененные файлы

### Новые файлы
[Если есть:]
- `path/File.java` — [что делает этот класс]

### Измененные файлы
- `path/File.java` — [кратко что изменено: добавлен метод X, изменена логика Y]

### Удаленные файлы
[Если есть:]
- `path/File.java` — [что удалили и почему]

---

## 🔧 Затронутые компоненты

[Перечисли пакеты/модули где есть изменения. Это помогает понять масштаб:]

- `com.company.query.parser` — [что изменилось]
- `com.company.query.executor` — [что изменилось]
- `com.company.settings` — [что изменилось]
- `com.company.util` — [вспомогательные изменения]

---

## ⚠️ КРИТИЧНО: Изменения в Query Language

**Это самая важная секция для тимлида!**

[Если НЕТ изменений в командах/парсинге/выполнении запросов:]
Изменений в языке запросов не обнаружено.

[Если ЕСТЬ изменения:]

### Новые команды
- `percentile(field, 95)` — вычисление процентилей
- `rare(field)` — поиск редких значений

### Измененные команды
- `stats avg(field)` — теперь корректно обрабатывает null (раньше игнорировал)
- `sort` — добавлена опция `-desc` для сортировки по убыванию

### Удаленные команды (BREAKING CHANGES)
- `timechart` — удалена устаревшая команда (deprecated с версии 2.0)

### Изменения в поведении
[Опиши как изменилось поведение существующих команд:]
- Команда `stats count()` теперь возвращает 0 вместо null для пустых результатов
- Приоритет операторов изменен: `AND` теперь выше чем `OR`

---

## ⚙️ Системные настройки

[Если НЕТ изменений:]
Изменений в системных настройках не обнаружено.

[Если ЕСТЬ изменения:]

### Новые настройки
- `query.max_depth` — ограничение глубины вложенности запросов (default: 10)

### Измененные настройки
- `query.timeout` — увеличен с 30s до 60s (для медленных кластеров)

### Удаленные настройки
- `legacy_mode` — удалена поддержка старого формата

**Риски:** [Объясни какие могут быть последствия изменения настроек]

---

## 🔗 Зависимости между файлами

[Эта секция помогает понять связанность изменений:]

**Связанные изменения в этом MR:**
- `QueryParser.java` добавил метод `parsePercentile()`
  - ✓ `PercentileCommand.java` использует этот метод (добавлен в этом же MR)

- `QueryExecutor.java` изменил сигнатуру `execute(Query q, Context ctx)`
  - ✓ `StatsCommand.java` обновил вызов под новую сигнатуру

**Потенциальные проблемы:**
[Если есть изменения, которые могут требовать правок в других местах:]
- `UserService.getUserById()` теперь возвращает Optional вместо null
  - ⚠️ Проверь все места вызова — могут быть NullPointerException

---

## 🎯 Что нужно проверить при ревью

[Подсказки тимлиду — на что обратить внимание:]

### Обязательно проверить:
- [ ] Backward compatibility для Query Language (не сломаются ли существующие запросы)
- [ ] Обработка null/edge cases в новых командах
- [ ] Влияние изменений системных настроек на production

### Желательно проверить:
- [ ] Есть ли тесты для новых команд
- [ ] Обновлена ли документация
- [ ] Нет ли дублирования кода

### Можно пропустить:
- Мелкие рефакторинги внутренних классов
- Изменения в утилитах (если не влияют на бизнес-логику)

---

ПРАВИЛА:
1. Пиши для тимлида, который может быть не в контексте проекта
2. Объясняй "что и зачем", а не только "что изменилось"
3. Фокус на Query Language и системных настройках
4. Выделяй breaking changes явно
5. Если секция пустая — пиши "не обнаружено" (не пропускай секции)
6. Будь конкретным — упоминай имена классов/методов
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