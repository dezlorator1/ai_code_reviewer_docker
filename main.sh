#!/bin/bash

# Останавливаем скрипт при любой ошибке
set -e

# === Configuration loading ===

# 1. Определяем директорию, где находится ЭТОТ скрипт
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yml"

# Проверка наличия yq
if ! command -v yq &> /dev/null; then
    echo "ERROR: yq is not installed. Install: pip install yq"
    exit 1
fi

# Загружаем пути из конфига
LOG_DIR=$(yq -r '.paths.LOG_DIR' "$CONFIG_FILE")
OUT_DIR=$(yq -r '.paths.OUT_DIR' "$CONFIG_FILE")
CHUNKS_DIR=$(yq -r '.paths.CHUNKS_DIR' "$CONFIG_FILE")
DIFF_DIR=$(yq -r '.paths.DIFF_DIR' "$CONFIG_FILE")
SUMMARY_FILE=$(yq -r '.paths.SUMMARY_FILE' "$CONFIG_FILE")

# =============================

# Корневая папка со всеми проектами (фиксированная)
PROJECTS_ROOT="/projects"

# 2. Парсинг аргументов
DIFF_FILES=""           # Список diff файлов через запятую
PROJECT_NAMES=""        # Список имен проектов через запятую
CUSTOM_OUTPUT=""        # Кастомное имя выходного файла (опционально)

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --diffs)
            DIFF_FILES="$2"
            shift 2
            ;;
        --names)
            PROJECT_NAMES="$2"
            shift 2
            ;;
        --output)
            CUSTOM_OUTPUT="$2"
            shift 2
            ;;
        *)
            echo "Ошибка: Неизвестный параметр: $1"
            echo ""
            echo "Использование:"
            echo "  $0 --diffs <diff1,diff2,...> --names <name1,name2,...> [--output <filename>]"
            echo ""
            echo "Параметры:"
            echo "  --diffs     Список diff файлов через запятую (обязательно)"
            echo "  --names     Список имен проектов через запятую (обязательно)"
            echo "  --output    Имя выходного файла (опционально, default: summary.md)"
            echo ""
            echo "Примеры:"
            echo "  $0 --diffs /inputs/rsm-3078.diff --names sm-rsm"
            echo "  $0 ---diffs /inputs/sm-3007.diff,/inputs/tools-3007.diff --names elastic-pql-plugin,sm-tools --output 3007.md"
            echo ""
            echo "Примечание: все проекты ищутся в /projects/<name>"
            exit 1
            ;;
    esac
done

# 3. Применяем кастомное имя файла если указано
if [ -n "$CUSTOM_OUTPUT" ]; then
    # Проверяем что это просто имя файла (без пути)
    if [[ "$CUSTOM_OUTPUT" == *"/"* ]]; then
        echo "Ошибка: --output должен быть именем файла, а не путем"
        echo "Правильно: --output my-report.md"
        echo "Неправильно: --output /some/path/report.md"
        exit 1
    fi

    # Обновляем путь к summary файлу
    OUTPUT_DIR=$(dirname "$SUMMARY_FILE")
    SUMMARY_FILE="$OUTPUT_DIR/$CUSTOM_OUTPUT"
    echo "Используется кастомное имя файла: $CUSTOM_OUTPUT"
fi

# 4. Валидация аргументов
if [ -z "$DIFF_FILES" ] || [ -z "$PROJECT_NAMES" ]; then
    echo "Ошибка: Не заданы обязательные аргументы."
    echo ""
    echo "Использование:"
    echo "  $0 --diffs <diff1,diff2,...> --names <name1,name2,...> [--output <filename>]"
    exit 1
fi

# Преобразуем строки с запятыми в массивы
IFS=',' read -ra DIFF_ARRAY <<< "$DIFF_FILES"
IFS=',' read -ra NAME_ARRAY <<< "$PROJECT_NAMES"

# Проверка что количество совпадает
if [ "${#DIFF_ARRAY[@]}" -ne "${#NAME_ARRAY[@]}" ]; then
    echo "Ошибка: Количество diff файлов (${#DIFF_ARRAY[@]}) и имен (${#NAME_ARRAY[@]}) не совпадает!"
    exit 1
fi

# Проверка существования файлов
for diff in "${DIFF_ARRAY[@]}"; do
    if [ ! -f "$diff" ]; then
        echo "Ошибка: Diff файл не найден: $diff"
        exit 1
    fi
done

# Проверка существования проектов
for name in "${NAME_ARRAY[@]}"; do
    project_path="$PROJECTS_ROOT/$name"
    if [ ! -d "$project_path" ]; then
        echo "Ошибка: Проект не найден: $project_path"
        echo "Убедитесь что папка '$name' существует в /projects/"
        exit 1
    fi
done

echo "=========================================="
echo "Запуск пайплайна автоматического ревью"
echo "=========================================="
echo "Проекты:"
for i in "${!NAME_ARRAY[@]}"; do
    echo "  [$((i+1))] ${NAME_ARRAY[$i]}"
    echo "      Diff:    ${DIFF_ARRAY[$i]}"
    echo "      Path:    $PROJECTS_ROOT/${NAME_ARRAY[$i]}"
done
echo "Результат: $SUMMARY_FILE"
echo "=========================================="

# 5. Подготовка директорий
echo "[1/6] Очистка рабочих директорий..."
rm -rf "${CHUNKS_DIR:?}"/*
rm -rf "${OUT_DIR:?}"/*
rm -rf "${DIFF_DIR:?}"/*

mkdir -p "$CHUNKS_DIR"
mkdir -p "$OUT_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$DIFF_DIR"

# 6. Объединение diff файлов
echo "[2/6] Объединение diff файлов из нескольких проектов..."

python3 "$SCRIPT_DIR/merge_diffs.py" \
    --diffs ${DIFF_ARRAY[@]} \
    --names ${NAME_ARRAY[@]}

MERGED_DIFF="$DIFF_DIR/merged.diff"

if [ ! -f "$MERGED_DIFF" ]; then
    echo "Ошибка: Не удалось создать объединенный diff"
    exit 1
fi

# 7. Извлечение глобального контекста MR
echo "[3/6] Анализ глобального контекста MR..."
python3 "$SCRIPT_DIR/extract_mr_context.py" --diff "$MERGED_DIFF"

# 8. Разбиение diff на чанки
echo "[4/6] Разбиение diff файла на чанки..."
"$SCRIPT_DIR/split_by_class.sh" "$MERGED_DIFF"

# Проверка, появились ли файлы
if [ -z "$(ls -A "$CHUNKS_DIR")" ]; then
   echo "Ошибка: Чанки не созданы. Проверьте содержимое diff файлов."
   exit 1
fi

# 9. Запуск ревью по чанкам
echo "[5/6] Запуск анализа через LLM..."

# Передаем проекты как /projects/name1:/projects/name2:...
PROJECT_PATHS=()
for name in "${NAME_ARRAY[@]}"; do
    PROJECT_PATHS+=("$PROJECTS_ROOT/$name")
done
ALL_PROJECTS=$(IFS=:; echo "${PROJECT_PATHS[*]}")

"$SCRIPT_DIR/run_reviews.sh" "$ALL_PROJECTS"

# 10. Сборка итогового отчета
echo "[6/6] Генерация финального отчета..."

# Передаем кастомное имя файла в summarize_reviews.py если указано
if [ -n "$CUSTOM_OUTPUT" ]; then
    # Экспортируем переменную для использования в Python
    export CUSTOM_SUMMARY_FILE="$SUMMARY_FILE"
    python3 "$SCRIPT_DIR/summarize_reviews.py" --output "$SUMMARY_FILE"
else
    python3 "$SCRIPT_DIR/summarize_reviews.py"
fi

echo "=========================================="
echo "✅ Готово! Результат записан в:"
echo "$SUMMARY_FILE"
echo "=========================================="