import logging
from pathlib import Path
from datetime import datetime
import requests
import os
import yaml
import argparse


# Определяем путь к конфигу
config_path = Path(__file__).parent / "config.yml"

# --- Читаем конфиг ---
with open(config_path) as f:
    config = yaml.safe_load(f)

# --- Используем ---
RESULTS_DIR = Path(config['paths']['OUT_DIR'])
SUMMARY_PATH = Path(config['paths']['SUMMARY_PATH'])
DEFAULT_OUT_FILE    = Path(config['paths']['SUMMARY_FILE'])
LOG_FILE    = Path(config['paths']['LOG_FILE'])
MR_CONTEXT_FILE = Path(config['paths']['OUT_DIR']) / "mr_context.md"

API_URL = config['llm']['api_url']
MODEL = config['llm']['model']
MAX_TOKENS = config['llm']['max_tokens']

# ==== LOGGING ====
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

# ==== PROMPT ====
SUMMARY_PROMPT = """Ты — финальное звено в цепочке анализа Merge Request.

**Твоя роль:** Создать ИТОГОВЫЙ ОТЧЕТ для Тимлида.

**Контекст:**
- Тимлид управляет множеством проектов
- Он НЕ в контексте этого конкретного MR
- Ему нужна четкая информация для принятия решения: мержить / доработать / заблокировать

**У тебя есть два источника данных:**
1. **MR CONTEXT** — глобальная цель MR и breaking changes на уровне архитектуры
2. **FILE REVIEWS** — детальный анализ каждого файла с найденными багами

---

### ИСТОЧНИК 1: MR CONTEXT
{mr_context}

---

### ИСТОЧНИК 2: FILE REVIEWS
{reviews}

---

**ТВОЯ ЗАДАЧА:**

1. **Синтезируй информацию:**
   - Возьми цель MR из контекста
   - Собери ВСЕ breaking changes (из контекста + из file reviews)
   - Агрегируй баги по уровням (убери дубликаты, сгруппируй похожие)

2. **Создай структурированный отчет:**
   - Вердикт (можно мержить / есть проблемы / блокирующие проблемы)
   - Суть изменений
   - Breaking changes
   - Сводка багов
   - Техническая сводка

3. **Правила агрегации:**
   - Если одна и та же проблема в 5 файлах — опиши ОДИН раз, укажи все файлы
   - Не копируй весь текст из reviews — обобщай
   - Фокусируйся на критичном

---

**ФОРМАТ ВЫВОДА:**

# 🛡️ Отчет по Code Review

**Дата:** {timestamp}
**Файлов проверено:** {files_count}

---

## 🚦 ВЕРДИКТ

[Выбери ОДИН вариант и напиши жирным:]

**✅ ВЫГЛЯДИТ БЕЗОПАСНО**
Багов не найдено, breaking changes согласованы, можно мержить.

**⚠️ ЕСТЬ ЗАМЕЧАНИЯ**
Найдены баги уровня High/Medium. Требуется доработка перед мержем.

**🛑 БЛОКИРУЮЩИЕ ПРОБЛЕМЫ**
Найдены Critical баги, неожиданные breaking changes, или серьезные архитектурные проблемы.

---

## 🎯 СУТЬ ИЗМЕНЕНИЙ

[Из MR Context — объясни Тимлиду что и зачем делается]

**Цель:**
[Бизнес-цель MR в 1-2 предложениях]

**Реализация:**
[Краткое техническое описание: какие модули затронуты, что добавлено, что изменено]

---

## 💥 BREAKING CHANGES

[КРИТИЧНО: Соберй ВСЕ breaking changes из MR Context и File Reviews]

[Если НЕТ:]
Не обнаружено.

[Если ЕСТЬ, структурируй по категориям:]

### Query Language
- **Удалена команда `timechart`** — дашборды с этой командой сломаются
- **Изменено поведение `stats count()`** — возвращает 0 вместо null

### Публичное API
- **Удален метод `QueryExecutor.executeLegacy()`** — внешние интеграции сломаются

### Системные настройки
- **Изменен default `query.timeout`** с 30s на 60s

**Влияние на пользователей:**
[Конкретно опиши что произойдет в production]

---

## 🐛 НАЙДЕННЫЕ ПРОБЛЕМЫ (Сводка)

[Агрегируй баги из всех File Reviews. Убери дубликаты. Сгруппируй похожие.]

[Если проблем НЕТ:]
Проблем не обнаружено. Код выглядит качественно.

[Если ЕСТЬ:]

### 🔴 CRITICAL

[Формат для каждой проблемы:]
**[Номер]. [Краткое название]**
- **Суть:** [Что не так]
- **Где:** [Название проекта, список файлов через запятую]
- **Влияние:** [Как упадет production]

**Пример:**
**1. NPE в обработке null значений**
- **Суть:** Методы не проверяют null перед .toString()
- **Где:** `main_plugin` `StatsCommand.java:45`, `AggregationExecutor.java:120`
- **Влияние:** Production упадет с NPE при первом же null

---

### 🟡 HIGH

**1. [Название проблемы]**
- **Суть:** ...
- **Где:** ...
- **Влияние:** ...

---

### 🟢 MEDIUM

[Можно короче, списком:]
- Отсутствует валидация параметров в `QueryParser.java`, `ExecutionEngine.java`
- Неоптимальный алгоритм сортировки в `ResultSorter.java` (может быть медленным на больших данных)

---

### ⚪ LOW

[Упомяни только если их очень много, иначе пропусти эту секцию]
- Стилистические замечания (10+ файлов)

---

## 📊 ТЕХНИЧЕСКАЯ СВОДКА

[Из MR Context — что было сделано технически]

**Масштаб:**
- Новых классов: N
- Измененных классов: M
- Удаленных классов: K

**Затронутые модули:**
- `com.company.query.parser` — [что изменилось]
- `com.company.query.commands` — [что изменилось]

**Рефакторинги:**
[Если были значимые рефакторинги которые НЕ являются багами:]
- Выделена валидация в отдельный класс `QueryValidator`
- Удалены deprecated утилиты из `com.company.legacy`

---

**ПРАВИЛА АГРЕГАЦИИ:**
1. **Синтезируй, не копируй:** Если в 5 файлах одна проблема — опиши раз, укажи все файлы
2. **Убирай шум:** Файлы без проблем не упоминай
3. **Фокус на критичном:** Breaking changes и CRITICAL баги — детально, LOW — можно пропустить
4. **Будь конкретным:** Называй файлы, строки, классы
5. **Пиши для Тимлида:** Ясно, структурировано, actionable

**НЕ ДОБАВЛЯЙ:**
- Секцию "Рекомендации" — её не нужно
- Длинные цитаты кода
- Повторения информации
"""

# ==== LLM CALL ====
def load_mr_context():
    """Load MR global context if available."""
    if MR_CONTEXT_FILE.exists():
        context = MR_CONTEXT_FILE.read_text(errors="ignore")
        log.info(f"MR_CONTEXT LOADED size={len(context)} bytes")
        return context
    else:
        log.warning(f"MR_CONTEXT FILE NOT FOUND: {MR_CONTEXT_FILE}")
        return "MR context not available."

def call_llm(prompt):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Ты — технический лид, специализирующийся на ревью OpenSearch плагинов с языками запросов. Твой приоритет — выявить изменения, влияющие на бизнес-логику запросов."},
            {"role": "user", "content": prompt}
        ],
        "temperature": config['llm']['temperature'],
        "max_tokens": MAX_TOKENS
    }

    log.info("SUMMARY LLM REQUEST START")
    start = datetime.now()

    r = requests.post(API_URL, json=payload, timeout=600)
    r.raise_for_status()

    dt = (datetime.now() - start).total_seconds()
    log.info(f"SUMMARY LLM REQUEST FINISH time={dt}s status={r.status_code}")

    return r.json()["choices"][0]["message"]["content"]

# ==== MAIN ====
def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="Summarize code reviews")
    parser.add_argument("--output", help="Custom output filename (optional, default from config)")
    args = parser.parse_args()

    # Determine output file
    OUT_FILE = SUMMARY_PATH / (args.output or DEFAULT_OUT_FILE)

    log.info("SUMMARY START")
    log.info(f"Output file: {OUT_FILE}")
    log.info("SUMMARY START")

    # Load MR context
    mr_context = load_mr_context()

    if not RESULTS_DIR.exists():
        log.error(f"RESULTS DIR NOT FOUND: {RESULTS_DIR}")
        return

    reviews = []
    for f in sorted(RESULTS_DIR.glob("*.md")):
        # Skip mr_context.md itself
        if f.name == "mr_context.md":
            continue
        text = f.read_text(errors="ignore")
        reviews.append(f"\n# File: {f.name}\n{text}\n")

    if not reviews:
        log.warning("NO REVIEW FILES FOUND")
        return

    all_reviews = "\n".join(reviews)
    files_count = len(reviews)
    log.info(f"LOADED REVIEWS chars={len(all_reviews)} files={files_count}")

    # Hard cap context to avoid OOM / context overflow
    MAX_CHARS = 250_000   # ~100k tokens rough upper bound
    if len(all_reviews) > MAX_CHARS:
        log.warning(f"REVIEWS TOO LARGE ({len(all_reviews)} chars), TRUNCATING TO {MAX_CHARS}")
        all_reviews = all_reviews[-MAX_CHARS:]

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = SUMMARY_PROMPT.format(
        reviews=all_reviews,
        mr_context=mr_context,
        timestamp=timestamp,
        files_count=files_count
    )
    log.info(f"SUMMARY PROMPT SIZE chars={len(prompt)}")

    summary = call_llm(prompt)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(summary)

    log.info(f"SUMMARY WRITTEN {OUT_FILE} bytes={len(summary)}")
    log.info("SUMMARY END")

    # Print summary
    print(f"\n{'='*60}")
    print(f"✅ Сводный отчет создан!")
    print(f"📄 Файл: {OUT_FILE}")
    print(f"📊 Проанализировано файлов: {len(reviews)}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()