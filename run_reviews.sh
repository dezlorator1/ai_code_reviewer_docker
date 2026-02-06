#!/bin/bash

set -euo pipefail

# === Configuration loading ===

# 1. Определяем директорию, где находится ЭТОТ скрипт (независимо от того, откуда его вызвали)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yml"

# Проверка наличия yq
if ! command -v yq &> /dev/null; then
    echo "ERROR: yq is not installed. Install: pip install yq"
    exit 1
fi

# 2. Проверяем наличие конфига и загружаем его
LOG_DIR=$(yq -r '.paths.LOG_DIR' "$CONFIG_FILE")
LOG_FILE=$(yq -r '.paths.LOG_FILE' "$CONFIG_FILE")
OUT_DIR=$(yq -r '.paths.OUT_DIR' "$CONFIG_FILE")
CHUNKS_DIR=$(yq -r '.paths.CHUNKS_DIR' "$CONFIG_FILE")
SCRIPT_PATH=$(yq -r '.paths.SCRIPT_PATH' "$CONFIG_FILE")
# =============================

SCRIPT_NAME="$(basename "$0")"
PROJECT_ROOT="$1"
# Создаем директории, если их нет (переменные берутся из конфига)
mkdir -p "$OUT_DIR"
mkdir -p "$LOG_DIR"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [$SCRIPT_NAME] $1" | tee -a "$LOG_FILE"
}

log "START script"

# Проверяем, есть ли файлы для обработки, чтобы скрипт не падал на *.diff, если папка пуста
# (shopt -s nullglob позволяет циклу не запускаться, если файлов нет)
shopt -s nullglob
FILES=("$CHUNKS_DIR"/*.diff)

if [ ${#FILES[@]} -eq 0 ]; then
    log "No .diff files found in $CHUNKS_DIR"
else
    for chunk in "${FILES[@]}"; do
        name=$(basename "$chunk" .diff)
        log "START chunk=$name file=$chunk"

        # Формируем команду (для лога)
        CMD="python3 $SCRIPT_PATH --chunk \"$chunk\" --project \"$PROJECT_ROOT\" --out \"$OUT_DIR/$name.md\""
        
        log "DRY-RUN CMD: $CMD"
        
        # Запускаем реально
        python3 "$SCRIPT_PATH" \
          --chunk "$chunk" \
          --project "$PROJECT_ROOT" \
          --out "$OUT_DIR/$name.md"

        log "END chunk=$name"
    done
fi

log "FINISH script"