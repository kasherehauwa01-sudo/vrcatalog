# Timeweb/VPS deploy snippets

- `nginx.conf` — пример внешнего reverse proxy для домена `kvasmix.ru` и подпапки `/vr/catalog/`.
- `vrcatalog.service` — опциональный systemd unit, который поднимает Docker Compose stack после перезагрузки сервера.

Основной способ запуска описан в корневом `README.md`: `docker compose up -d --build`.

## Скрипт безопасного обновления

Установите отслеживаемый Git-ом скрипт вместо локальной версии:

```bash
install -m 0755 \
  /var/www/html/vr/vrcatalog/deploy/timeweb/update_vrcatalog.sh \
  /var/www/html/vr/update_vrcatalog.sh
```

Скрипт не очищает Docker build-кэш до сборки и не заменяет работающие контейнеры,
пока новые образы не будут успешно собраны. Сборка повторяется три раза с
интервалом 15 секунд. Параметры можно переопределить:

```bash
VRCATALOG_BUILD_ATTEMPTS=5 \
VRCATALOG_RETRY_DELAY=30 \
/var/www/html/vr/update_vrcatalog.sh
```

Очистка неиспользуемого build-кэша после успешного запуска по умолчанию
отключена. При необходимости включите её явно:

```bash
VRCATALOG_PRUNE_AFTER_UPDATE=1 /var/www/html/vr/update_vrcatalog.sh
```

## Ошибка DNS Docker Hub

Сообщение `lookup registry-1.docker.io on 127.0.0.53:53: server misbehaving`
означает проблему DNS на сервере, а не ошибку Dockerfile. Проверьте:

```bash
getent hosts registry-1.docker.io
resolvectl status
systemctl status systemd-resolved --no-pager
```

Безопасный первый вариант восстановления системного резолвера:

```bash
systemctl restart systemd-resolved
getent hosts registry-1.docker.io
```

Если имя по-прежнему не разрешается, проверьте DNS-настройки VPS и `/etc/resolv.conf`.
Не отключайте `systemd-resolved` и не перезаписывайте `/etc/resolv.conf`, не выяснив,
как сеть настраивается у вашего хостинг-провайдера. После восстановления DNS
повторно запустите `/var/www/html/vr/update_vrcatalog.sh`.
