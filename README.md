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

- `frontend` — Nginx + собранный React/Vite frontend; также проксирует `/vr/catalog/api/` в backend.
- `backend` — FastAPI API.
- `postgres` — PostgreSQL с хранением данных в Docker volume.

Volumes:

- `postgres_data` — данные PostgreSQL.
- `uploads_data` — загруженные XML-файлы/служебные загрузки.

## Важные URL

```text
Frontend:       https://kvasmix.ru/vr/catalog/
API:            https://kvasmix.ru/vr/catalog/api/
OpenAPI docs:   https://kvasmix.ru/vr/catalog/api/docs
Healthcheck:    https://kvasmix.ru/vr/catalog/api/health
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
SECRET_KEY=change-this-secret-key
INTERNAL_API_TOKEN=replace-with-a-long-random-token
POSTGRES_DB=vrcatalog
POSTGRES_USER=vrcatalog
POSTGRES_PASSWORD=vrcatalog_password
VITE_BASE_PATH=/vr/catalog/
```

`BASE_PATH` нужен backend для корректного OpenAPI за reverse proxy. `VITE_BASE_PATH` нужен Vite для сборки ассетов под подпапку `/vr/catalog/`. В frontend API-ссылки строятся от `import.meta.env.BASE_URL`, поэтому нет отдельного абсолютного URL `/api`.

`INTERNAL_API_TOKEN` используется только backend-to-backend запросами. Сгенерировать токен можно командой `openssl rand -hex 32`; его нельзя добавлять в frontend или передавать в URL.

## Внутреннее API ответственных менеджеров

Каталог является источником названия товара и ответственного менеджера для других сервисов. Оба endpoint требуют заголовок `X-Internal-Token`, скрыты из OpenAPI/Swagger и возвращают HTTP 401 при отсутствующем или неверном токене.

Один товар (диагностика):

```bash
curl -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  "https://kvasmix.ru/vr/catalog/api/internal/products/by-article/10001"
```

```json
{
  "ok": true,
  "article": "10001",
  "found": true,
  "product_id": 15,
  "name": "Товар А",
  "manager_id": null,
  "manager_name": "Иванов Иван"
}
```

Массовый запрос (до 1000 позиций):

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  -d '{"articles":["10001","10002","00123"]}' \
  "https://kvasmix.ru/vr/catalog/api/internal/products/by-articles"
```

```json
{
  "ok": true,
  "items": [
    {
      "article": "10001",
      "found": true,
      "product_id": 15,
      "name": "Товар А",
      "manager_id": null,
      "manager_name": "Иванов Иван"
    },
    {
      "article": "10002",
      "found": true,
      "product_id": 18,
      "name": "Товар Б",
      "manager_id": null,
      "manager_name": null
    },
    {
      "article": "00123",
      "found": false,
      "product_id": null,
      "name": null,
      "manager_id": null,
      "manager_name": null
    }
  ]
}
```

Порядок и повторы сохраняются. Уникальные артикулы ищутся одним SQL-запросом по индексу `ix_products_article`, поэтому повторный артикул не создаёт дополнительного обращения к БД.

### Текущее хранение менеджера и совместимое развитие

Характеристика «Менеджер» импортируется из XML одновременно в универсальную таблицу `product_properties` и в текстовый столбец `products.manager`. Таблицы сотрудников, внутреннего идентификатора менеджера и внешнего ключа на сотрудника сейчас нет, поэтому API возвращает `manager_id: null`, а ФИО — в `manager_name`. Существующий импорт и модель данных не изменяются.

Если стабильный справочник сотрудников появится в источнике данных, безопасный переход состоит из следующих этапов: создать отдельный справочник с уникальным внешним ID; добавить nullable-связь товара с ним; продолжать заполнять и возвращать текстовое имя; сопоставить исторические записи; начать возвращать ID только для надёжно сопоставленных менеджеров. Это сохраняет совместимость потребителей, которые уже используют `manager_name`.

Каждое успешное или отклонённое по токену обращение записывается в `service_logs` с событием `internal_api_request`: дата и время находятся в `created_at`, а JSON в `message` содержит endpoint, число артикулов, длительность, числа найденных/ненайденных товаров и HTTP-код. Токен, заголовки и сами артикулы не журналируются.

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
