import logging
from pathlib import Path
from datetime import datetime
import requests
import os
import yaml


# Определяем путь к конфигу
config_path = Path(__file__).parent / "config.yml"

# --- Читаем конфиг ---
with open(config_path) as f:
    config = yaml.safe_load(f)

# --- Используем ---
RESULTS_DIR = Path(config['paths']['OUT_DIR'])
OUT_FILE    = Path(config['paths']['SUMMARY_FILE'])
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
SUMMARY_PROMPT = """Ты — умный ассистент Тимлида. Твоя задача — составить финальный сводный отчет по Merge Request (MR).

Тимлид управляет множеством проектов и не погружен в детали этого конкретного MR. Ему нужна "выжимка", чтобы принять решение:
1. Мержить
2. Отправлять на доработку (есть баги)
3. Блокировать (есть критичные проблемы архитектуры или breaking changes)

У тебя есть два источника информации:
1. **MR CONTEXT** — глобальная цель MR (зачем это делалось).
2. **FILE REVIEWS** — детальный анализ каждого файла с найденными проблемами.

---

### ИСТОЧНИК 1: MR CONTEXT
{mr_context}

---

### ИСТОЧНИК 2: FILE REVIEWS
{reviews}

---

### ИНСТРУКЦИЯ ПО СОСТАВЛЕНИЮ ОТЧЕТА:

1. **Синтезируй, а не копируй:** Не перечисляй файлы списком. Обобщай. Если в 5 файлах одна и та же проблема — напиши о ней один раз и перечисли файлы в скобках.
2. **Фокус на "Зачем":** В начале объясни Тимлиду бизнес-цель изменений (из MR Context) и как она была реализована технически (из File Reviews).
3. **Отсей шум:**
   - Если в ревью файла написано "✅ Критических проблем не обнаружено" и нет замечаний — не упоминай этот файл в списке проблем.
   - Мелкие замечания по стилю (LOW) упоминай, только если их очень много.
4. **Breaking Changes — это приоритет №1:** Любые изменения Query Language, публичных API или настроек выноси в отдельный блок.

---

### ФОРМАТ ВЫВОДА (Markdown, на русском языке):

# 🛡️ Отчет по Code Review

**Дата:** {timestamp}
**Файлов проверено:** {files_count}

## 🚦 Вердикт
[Выбери один вариант и выдели жирным:]
- **✅ ВЫГЛЯДИТ БЕЗОПАСНО** (Багов нет, тесты ок, логика понятна)
- **⚠️ ЕСТЬ ЗАМЕЧАНИЯ** (Найдены ошибки уровня High/Medium, нужен фикс перед мержем)
- **🛑 БЛОКИРУЮЩИЕ ПРОБЛЕМЫ** (Найдены Critical баги, уязвимости или неожиданные Breaking Changes)

---

## 🎯 Суть изменений
[Кратко, для Тимлида, который не в контексте:]
**Цель:** [Из MR Context - зачем этот MR нужен бизнесу/проекту]
**Реализация:** [Кратко: какие основные модули затронуты, добавлены ли новые классы, был ли рефакторинг]

---

## 💥 Breaking Changes & Влияние на пользователей
[Если есть — опиши подробно. Если нет — "Не обнаружено".]
- **API/Query Language:** [Например: Изменено поведение параметра в команде `stats`. Старые дашборды сломаются.]
- **Конфигурация:** [Например: Изменен дефолтный таймаут.]

---

## 🐛 Найденные проблемы (Сводка)

[Сгруппируй проблемы из всех файлов. Если проблем нет — пропусти секцию.]

### 🔴 CRITICAL
[Баги, NPE, Race Conditions, Security]
1. **[Название проблемы]**
   - **Суть:** [Описание]
   - **Где:** `File.java` (строка N), `AnotherFile.java`
   - **Влияние:** [Как упадет прод]

### 🟡 HIGH
[Ошибки логики, выбор алгоритмов, производительность]
1. **[Название]**
   - **Суть:** ...
   - **Где:** `File.java`

### 🟢 MEDIUM
[Код с запашком, отсутствие валидации]
- [Список замечаний]

### ⚪ Незначительные замечания (LOW)
---

## ℹ️ Технические детали и Рефакторинг
[Здесь упомяни изменения, которые не являются багами, но важны для понимания масштаба. Например, удаление старых утилит, переименование внутренних методов, изменения в структуре пакетов.]

---

## 📝 Рекомендации для Тимлида
[Советы: что проверить вручную, на что обратить внимание при деплое]
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