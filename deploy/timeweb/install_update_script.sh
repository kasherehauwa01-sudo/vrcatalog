#!/usr/bin/env bash

set -Eeuo pipefail

TARGET_PATH="${VRCATALOG_UPDATE_PATH:-/var/www/html/vr/update_vrcatalog.sh}"
TRACKED_SCRIPT="${VRCATALOG_TRACKED_UPDATE_SCRIPT:-/var/www/html/vr/vrcatalog/deploy/timeweb/update_vrcatalog.sh}"

if [[ ! -x "$TRACKED_SCRIPT" ]]; then
  printf 'Ошибка: актуальный скрипт не найден или не исполняемый: %s\n' "$TRACKED_SCRIPT" >&2
  exit 1
fi

install -d -m 0755 "$(dirname "$TARGET_PATH")"
temporary_path="$(mktemp "${TARGET_PATH}.tmp.XXXXXX")"
trap 'rm -f "$temporary_path"' EXIT

cat >"$temporary_path" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$TRACKED_SCRIPT" "\$@"
EOF

chmod 0755 "$temporary_path"
mv -f "$temporary_path" "$TARGET_PATH"
trap - EXIT

printf 'Wrapper обновления установлен: %s -> %s\n' "$TARGET_PATH" "$TRACKED_SCRIPT"
printf 'Теперь запускайте: %s\n' "$TARGET_PATH"
