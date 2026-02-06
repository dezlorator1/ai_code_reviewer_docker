#!/bin/bash
set -e

# 1. Применяем переменные окружения к config.yml
# Используем python для надежного обновления YAML
python3 -c "
import yaml
import os

config_path = '/app/config.yml'
with open(config_path) as f:
    config = yaml.safe_load(f)

# Перезаписываем настройки LLM, если заданы переменные окружения
if os.environ.get('LLM_API_URL'):
    config['llm']['api_url'] = os.environ['LLM_API_URL']
if os.environ.get('LLM_MODEL'):
    config['llm']['model'] = os.environ['LLM_MODEL']
if os.environ.get('LLM_MAX_TOKENS'):
    config['llm']['max_tokens'] = int(os.environ['LLM_MAX_TOKENS'])
if os.environ.get('LLM_TEMPERATURE'):
    config['llm']['temperature'] = float(os.environ['LLM_TEMPERATURE'])

with open(config_path, 'w') as f:
    yaml.dump(config, f)
print('Config updated from environment variables.')
"

# 2. Передача управления главному скрипту
# Мы передаем все аргументы (--diff ... --project ...) в main.sh
exec ./main.sh "$@"