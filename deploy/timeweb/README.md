# Timeweb/VPS deploy snippets

- `nginx.conf` — пример внешнего reverse proxy для домена `kvasmix.ru` и подпапки `/vr/catalog/`.
- `vrcatalog.service` — опциональный systemd unit, который поднимает Docker Compose stack после перезагрузки сервера.

Основной способ запуска описан в корневом `README.md`: `docker compose up -d --build`.
