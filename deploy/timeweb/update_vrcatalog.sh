#!/usr/bin/env bash

set -Eeuo pipefail

REPO_DIR="${VRCATALOG_REPO_DIR:-/var/www/html/vr/vrcatalog}"
BUILD_ATTEMPTS="${VRCATALOG_BUILD_ATTEMPTS:-3}"
RETRY_DELAY="${VRCATALOG_RETRY_DELAY:-15}"
PRUNE_AFTER_UPDATE="${VRCATALOG_PRUNE_AFTER_UPDATE:-0}"

log() {
  printf '\n%s\n' "$1"
}

if [[ ! -d "$REPO_DIR/.git" ]]; then
  printf 'Ошибка: каталог репозитория не найден: %s\n' "$REPO_DIR" >&2
  exit 1
fi

if ! [[ "$BUILD_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'Ошибка: VRCATALOG_BUILD_ATTEMPTS должен быть положительным целым числом.\n' >&2
  exit 1
fi

cd "$REPO_DIR"

log "====================================="
printf ' Обновление VR Catalog\n'
printf '=====================================\n'

log "1. Получение изменений из Git..."
git pull --ff-only

log "2. Проверка доступа к Docker Registry..."
if getent hosts registry-1.docker.io >/dev/null 2>&1; then
  printf 'DNS Docker Registry доступен.\n'
else
  printf '%s\n' \
    'Предупреждение: registry-1.docker.io не разрешается через DNS.' \
    'Сборка всё равно будет запущена: Docker может использовать локальный кэш.' >&2
fi

log "3. Сборка образов..."
build_succeeded=0
for ((attempt = 1; attempt <= BUILD_ATTEMPTS; attempt += 1)); do
  printf 'Попытка сборки %d из %d...\n' "$attempt" "$BUILD_ATTEMPTS"
  if docker compose build; then
    build_succeeded=1
    break
  fi

  if ((attempt < BUILD_ATTEMPTS)); then
    printf 'Сборка не удалась. Повтор через %s сек.\n' "$RETRY_DELAY" >&2
    sleep "$RETRY_DELAY"
  fi
done

if ((build_succeeded == 0)); then
  printf '%s\n' \
    'Ошибка: новые образы не собраны. Работающие контейнеры не остановлены и не заменены.' \
    'Проверьте DNS командой: getent hosts registry-1.docker.io' \
    'После восстановления DNS повторно запустите этот скрипт.' >&2
  exit 1
fi

log "4. Запуск собранных контейнеров..."
docker compose up -d --no-build --remove-orphans
docker compose ps

if [[ "$PRUNE_AFTER_UPDATE" == "1" ]]; then
  log "5. Очистка неиспользуемого build-кэша после успешного запуска..."
  docker builder prune -f
else
  log "5. Build-кэш сохранён для устойчивости следующих обновлений."
fi

log "Обновление VR Catalog завершено успешно."
