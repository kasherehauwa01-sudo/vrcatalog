# VR Catalog

VR Catalog — веб-сервис просмотра товарного каталога с импортом XML в базу данных. Проект подготовлен для размещения на VPS в подпапке сайта:

```text
https://kvasmix.ru/vr/catalog/
```

Runtime не работает напрямую с XML: XML разбирается независимым модулем импорта, после чего поиск, фильтрация, карточки и экспорт читают данные только из PostgreSQL.

## Возможности

- Загрузка XML через кнопку **«Загрузить XML»**.
- Полная замена предыдущего каталога при импорте.
- Импорт товаров, кодов, названий, разделов, количества, описаний, изображений, аналогов и штрихкодов.
- Импорт любых типов цен без жесткого списка.
- Импорт остатков по каждому складу.
- Импорт всех свойств товара через универсальную таблицу свойств.
- Поиск без учета регистра по названию, коду, артикулу, описанию, бренду, производителю, штрихкодам и тегам.
- Автоматические фильтры по данным базы.
- Карточки товаров, детальная карточка, избранное, история просмотров и копирование полей.
- Экспорт найденных товаров в CSV и Excel.

## Docker Compose архитектура

Контейнеры:

- `frontend` — Nginx + собранный React/Vite frontend; также проксирует `/vr/catalog/api/` и `/vr/catalog/images/` в backend.
- `backend` — FastAPI API.
- `postgres` — PostgreSQL с хранением данных в Docker volume.

Volumes:

- `postgres_data` — данные PostgreSQL.
- `uploads_data` — загруженные XML-файлы/служебные загрузки.
- `images_data` — директория для изображений, которые отдаются через `/vr/catalog/images/...`.

## Важные URL

```text
Frontend:       https://kvasmix.ru/vr/catalog/
API:            https://kvasmix.ru/vr/catalog/api/
OpenAPI docs:   https://kvasmix.ru/vr/catalog/api/docs
Healthcheck:    https://kvasmix.ru/vr/catalog/api/health
Images:         https://kvasmix.ru/vr/catalog/images/...
```

Health endpoint возвращает:

```json
{"status":"ok"}
```

## Настройки `.env`

Скопируйте пример:

```bash
cp .env.example .env
```

Основные параметры:

```env
BASE_PATH=/vr/catalog
PORT=8080
DATABASE_URL=postgresql+psycopg://vrcatalog:vrcatalog_password@postgres:5432/vrcatalog
UPLOAD_DIR=/app/uploads
IMAGE_DIR=/app/images
SECRET_KEY=change-this-secret-key
POSTGRES_DB=vrcatalog
POSTGRES_USER=vrcatalog
POSTGRES_PASSWORD=vrcatalog_password
VITE_BASE_PATH=/vr/catalog/
```

`BASE_PATH` нужен backend для корректного OpenAPI за reverse proxy. `VITE_BASE_PATH` нужен Vite для сборки ассетов под подпапку `/vr/catalog/`. В frontend API-ссылки строятся от `import.meta.env.BASE_URL`, поэтому нет отдельного абсолютного URL `/api`.

## Быстрый деплой на VPS

```bash
git clone https://github.com/kasherehauwa01-sudo/vrcatalog.git
cd vrcatalog
cp .env.example .env
nano .env
docker compose up -d --build
```

Проверка контейнеров:

```bash
docker compose ps
```

Проверка API на сервере:

```bash
curl http://127.0.0.1:8080/vr/catalog/api/health
curl http://127.0.0.1:8080/vr/catalog/api/meta
```

Логи:

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f postgres
```

Остановка:

```bash
docker compose down
```

Остановка с удалением данных PostgreSQL:

```bash
docker compose down -v
```

## Пример reverse proxy Nginx на хосте VPS

Если на VPS уже есть внешний Nginx, оставьте `frontend` контейнер слушать локальный порт из `.env`, например `PORT=8080`, и проксируйте домен в контейнер:

```nginx
server {
    listen 80;
    server_name kvasmix.ru www.kvasmix.ru;

    client_max_body_size 200m;

    location /vr/catalog/ {
        proxy_pass http://127.0.0.1:8080/vr/catalog/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Prefix /vr/catalog;
    }
}
```

После изменения конфига:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Для HTTPS можно выпустить сертификат Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d kvasmix.ru -d www.kvasmix.ru
```

## React/Vite и подпапка `/vr/catalog/`

Frontend настроен на размещение не в корне сайта:

- `BrowserRouter` использует `basename="/vr/catalog/"`.
- Vite собирает проект с `base: "/vr/catalog/"` через `VITE_BASE_PATH`.
- Nginx внутри frontend-контейнера использует fallback `try_files ... /vr/catalog/index.html`, поэтому React Router корректно работает при обновлении страницы.
- API вызывается через `/vr/catalog/api/...`.
- Изображения доступны через `/vr/catalog/images/...`.

## Обновление проекта на VPS

```bash
cd vrcatalog
git pull
docker compose up -d --build
```

## Резервное копирование PostgreSQL

```bash
docker compose exec postgres pg_dump -U vrcatalog vrcatalog > backup_$(date +%F_%H%M).sql
```

Восстановление:

```bash
cat backup.sql | docker compose exec -T postgres psql -U vrcatalog vrcatalog
```

## Команды проверки для разработки

```bash
python -m compileall backend/app backend/alembic
```

```bash
docker compose config
```
