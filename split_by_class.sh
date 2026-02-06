#!/bin/bash

# === Configuration loading ===

# 1. Определяем директорию, где находится ЭТОТ скрипт (независимо от того, откуда его вызвали)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yml"


# Проверка наличия yq
if ! command -v yq &> /dev/null; then
    echo "ERROR: yq is not installed. Install: pip install yq"
    exit 1
fi
# =============================

CHUNKS_DIR=$(yq -r '.paths.CHUNKS_DIR' "$CONFIG_FILE")

DIFF_FILE="$1"

if [ -z "$DIFF_FILE" ]; then
  echo "Usage: $0 diff_file"
  exit 1
fi

if [ ! -f "$DIFF_FILE" ]; then
  echo "Diff file not found: $DIFF_FILE"
  exit 1
fi

echo "=== Splitting diff by files ==="

rm -rf "$CHUNKS_DIR"
mkdir -p "$CHUNKS_DIR"

awk -v outdir="$CHUNKS_DIR" '
BEGIN {
    file_index = 0
    chunk = ""
    filename = ""
}

# Start of new diff block
/^diff --git / {
    # save previous chunk
    if (chunk != "") {
        out = sprintf("%s/chunk_%04d.diff", outdir, file_index)
        print chunk > out
        close(out)
    }

    file_index++
    chunk = $0 "\n"
    next
}

# Append all lines
{
    chunk = chunk $0 "\n"
}

END {
    # save last chunk
    if (chunk != "") {
        out = sprintf("%s/chunk_%04d.diff", outdir, file_index)
        print chunk > out
        close(out)
    }
}
' "$DIFF_FILE"

echo "Done. Created $(ls -1 "$CHUNKS_DIR" | wc -l) chunks."
