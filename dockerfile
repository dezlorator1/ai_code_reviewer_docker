# Используем свежий стабильный Python
FROM python:3.12-slim

# Установка системных утилит
# dos2unix - лечит концы строк Windows
# git, curl, jq - нужны для работы скриптов
RUN apt-get update && apt-get install -y \
    git \
    curl \
    jq \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Устанавливаем зависимости глобально (venv в контейнере избыточен)
RUN pip install --no-cache-dir \
    requests \
    pyyaml \
    yq

# Копируем скрипты и конфиг
COPY *.py /app/
COPY *.sh /app/
COPY config.yml /app/

# 1. Лечим переносы строк (CRLF -> LF)
# 2. Делаем скрипты исполняемыми
RUN dos2unix /app/*.sh /app/*.py /app/*.yml && \
    chmod +x /app/*.sh /app/*.py

# Создаем папки для логов и временных файлов
RUN mkdir -p /app/output /app/logs /app/temp_chunks /app/temp_results

ENTRYPOINT ["/app/entrypoint.sh"]