# Timeweb/VPS deploy snippets

- `nginx.conf` — пример внешнего reverse proxy для домена `kvasmix.ru` и подпапки `/vr/catalog/`.
- `vrcatalog.service` — опциональный systemd unit, который поднимает Docker Compose stack после перезагрузки сервера.

Основной способ запуска описан в корневом `README.md`: `docker compose up -d --build`.

## Скрипт безопасного обновления

Запускайте непосредственно отслеживаемый Git-ом скрипт из репозитория:

```bash
/var/www/html/vr/vrcatalog/deploy/timeweb/update_vrcatalog.sh
```

Если требуется сохранить привычную команду `/var/www/html/vr/update_vrcatalog.sh`,
один раз установите wrapper:

```bash
/var/www/html/vr/vrcatalog/deploy/timeweb/install_update_script.sh
```

Wrapper не содержит логики обновления: он всегда запускает актуальный скрипт из
репозитория. Поэтому последующие `git pull` автоматически обновляют фактически
исполняемый код, а внешний путь больше не устаревает.

Не используйте старую отдельную копию `/var/www/html/vr/update_vrcatalog.sh`:
команда `git pull` обновляет файлы только внутри репозитория и не может заменить
этот внешний файл. Если в выводе шаг 2 называется «Очистка build-кэша Docker»,
запущена именно старая копия. У актуального скрипта шаг 2 называется «Проверка
доступа к Docker Registry».

Старый путь можно либо заменить wrapper-скриптом командой выше, либо удалить
после проверки прямого запуска:

```bash
rm -f /var/www/html/vr/update_vrcatalog.sh
```

Скрипт не очищает Docker build-кэш до сборки и не заменяет работающие контейнеры,
пока новые образы не будут успешно собраны. Сборка повторяется три раза с
интервалом 15 секунд. Параметры можно переопределить:

```bash
VRCATALOG_BUILD_ATTEMPTS=5 \
VRCATALOG_RETRY_DELAY=30 \
/var/www/html/vr/vrcatalog/deploy/timeweb/update_vrcatalog.sh
```

Очистка неиспользуемого build-кэша после успешного запуска по умолчанию
отключена. При необходимости включите её явно:

```bash
VRCATALOG_PRUNE_AFTER_UPDATE=1 \
  /var/www/html/vr/vrcatalog/deploy/timeweb/update_vrcatalog.sh
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
повторно запустите отслеживаемый скрипт:

```bash
/var/www/html/vr/vrcatalog/deploy/timeweb/update_vrcatalog.sh
```
