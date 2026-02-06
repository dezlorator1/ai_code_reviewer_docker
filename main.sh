#!/bin/bash

# Останавливаем скрипт при любой ошибке
set -e

# === Configuration loading ===

# 1. Определяем директорию, где находится ЭТОТ скрипт (независимо от того, откуда его вызвали)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yml"

# Проверка наличия yq
if ! command -v yq &> /dev/null; then
    echo "ERROR: yq is not installed. Install: pip install yq"
    exit 1
fi

LOG_DIR=$(yq -r '.paths.LOG_DIR' "$CONFIG_FILE")
OUT_DIR=$(yq -r '.paths.OUT_DIR' "$CONFIG_FILE")
CHUNKS_DIR=$(yq -r '.paths.CHUNKS_DIR' "$CONFIG_FILE")
SUMMARY_FILE=$(yq -r '.paths.SUMMARY_FILE' "$CONFIG_FILE")
# =============================

# 2. Парсинг аргументов
# Инициализируем переменные пустыми значениями
DIFF_FILE_PATH=""
TARGET_PROJECT_PATH=""

# Цикл по всем переданным аргументам
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --diff)
            DIFF_FILE_PATH="$2"
            shift 2 # Сдвигаем аргументы на 2 (сам флаг и его значение)
            ;;
        --project)
            TARGET_PROJECT_PATH="$2"
            shift 2
            ;;
        *)
            echo "Ошибка: Неизвестный параметр: $1"
            echo "Использование: $0 --diff <путь_до_diff> --project <путь_до_проекта>"
            exit 1
            ;;
    esac
done

# Проверка, что обязательные параметры были заданы
if [ -z "$DIFF_FILE_PATH" ] || [ -z "$TARGET_PROJECT_PATH" ]; then
    echo "Ошибка: Не заданы обязательные аргументы."
    echo "Использование: $0 --diff <путь_до_diff_файла> --project <путь_до_корня_проекта>"
    exit 1
fi

# Проверка существования входных данных
if [ ! -f "$DIFF_FILE_PATH" ]; then
    echo "Ошибка: Файл diff не найден: $DIFF_FILE_PATH"
    exit 1
fi

if [ ! -d "$TARGET_PROJECT_PATH" ]; then
    echo "Ошибка: Папка проекта не найдена: $TARGET_PROJECT_PATH"
    exit 1
fi

echo "=========================================="
echo "Запуск пайплайна автоматического ревью"
echo "Diff:    $DIFF_FILE_PATH"
echo "Project: $TARGET_PROJECT_PATH"
echo "=========================================="

# 3. Подготовка директорий
# Удаляем старые чанки и результаты, чтобы не смешивать с предыдущим запуском
echo "[1/5] Очистка рабочих директорий..."
rm -rf "${CHUNKS_DIR:?}"/*
rm -rf "${OUT_DIR:?}"/*

# Создаем директории, если их нет
mkdir -p "$CHUNKS_DIR"
mkdir -p "$OUT_DIR"
mkdir -p "$LOG_DIR"

# 4. Извлечение глобального контекста MR
echo "[2/5] Анализ глобального контекста MR..."
python3 $SCRIPT_DIR/extract_mr_context.py --diff "$DIFF_FILE_PATH"

# 5. Разбиение diff на чанки
echo "[3/5] Разбиение diff файла на чанки..."
# Предполагается, что split_by_class.sh берет путь из аргумента, 
# а сохраняет в CHUNKS_DIR (который он должен брать из env или конфига)

$SCRIPT_DIR/split_by_class.sh "$DIFF_FILE_PATH"

# Проверка, появились ли файлы
if [ -z "$(ls -A "$CHUNKS_DIR")" ]; then
   echo "Ошибка: Чанки не созданы. Проверьте содержимое diff файла."
   exit 1
fi

# 6. Запуск ревью по чанкам
echo "[4/5] Запуск анализа через LLM..."
# Передаем путь к проекту в run_reviews.sh

$SCRIPT_DIR/run_reviews.sh "$TARGET_PROJECT_PATH"

# 7. Сборка итогового отчета
echo "[5/5] Генерация финального отчета..."
# Предполагается, что summarize_reviews.py сам знает, откуда читать (OUT_DIR)
# и куда писать (SUMMARY_FILE) на основе config.env или зашитых путей.
# Если скрипт лежит не в текущей папке, укажите полный путь к нему.

python3 $SCRIPT_DIR/summarize_reviews.py

echo "=========================================="
echo "Готово! Результат записан в:"
echo "$SUMMARY_FILE"
echo "=========================================="