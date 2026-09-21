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

## API товаров по свойству для Sales Journal

Существующий endpoint списка товаров поддерживает защищённую межсервисную фильтрацию:

```text
GET /api/products?property=HoReCa&property_value=HoReCa&limit=10000&offset=0
```

При использовании `property` оба параметра (`property` и `property_value`) обязательны.
Название и значение очищаются от пробелов по краям, приводятся к нижнему регистру
и сравниваются в PostgreSQL целиком, без частичного поиска. Обычный `GET /api/products`
без этих параметров остаётся публичным и сохраняет прежний контракт.

Для межсервисного запроса используется `INTERNAL_API_TOKEN`. Sales Journal может
передать его стандартным Bearer-заголовком; прежний `X-Internal-Token` также поддерживается:

```bash
curl \
  -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
  "https://kvasmix.ru/vr/catalog/api/products?property=HoReCa&property_value=HoReCa&limit=10000"
```

Ответ — совместимый с Sales Journal корневой массив. В каждом товаре присутствуют
`id`, `article`, `code`, `name` и однозначный объект `properties`:

```json
[
  {
    "id": 123,
    "article": "A-001",
    "code": "000123",
    "name": "Название товара",
    "properties": {"HoReCa": "HoReCa"}
  }
]
```

`limit` допускает значения от 1 до 10000, `offset` — неотрицательное число.
Если результатов больше 10000, клиент последовательно увеличивает `offset` до получения
пустого массива. При отсутствии совпадений возвращаются HTTP 200 и `[]`. Отсутствующий
токен возвращает HTTP 401, неверный — HTTP 403, а передача только одного параметра
свойства — HTTP 422. Фильтрация выполняется SQL `EXISTS`; связанные свойства загружаются
одним дополнительным пакетным запросом, без N+1.

## Интеграция с Sales Journal

Для интерактивного подбора товаров предусмотрено отдельное read-only API:

* `GET /api/integration/product-filters` — реальные фильтры и первые 100 вариантов;
* `GET /api/integration/product-filters/{filter_key}/options` — поиск и пагинация
  вариантов (`search`, `page`, `page_size`, максимум 100);
* `POST /api/integration/products/search` — серверный поиск и подсчёт товаров.

Все маршруты требуют `Authorization: Bearer <INTERNAL_API_TOKEN>`. Отсутствующий
заголовок даёт 401, неверный токен — 403. Токен сравнивается в постоянное время и
не записывается в журналы. В CatalogVR задаётся `INTERNAL_API_TOKEN`; на стороне
Sales Journal тот же секрет можно хранить как `VRCATALOG_API_TOKEN`. Других
переменных окружения CatalogVR для интеграции не требуется.

Метаданные строятся из существующих полей `Product` (`section`, `manufacturer`,
`brand`, `manager`, `country`, `material`, `color`) и строк `ProductProperty`.
Свойства имеют стабильный для текущего источника ключ `property:<точное имя>`.
Тип всех существующих списочных фильтров — `multi_select`; варианты сортируются,
дубликаты удаляются. Если вариантов больше 100, `options_paginated` равен `true`
и Sales Journal должен загрузить их через endpoint `/options`.

Пример получения фильтров:

```bash
curl -H "Authorization: Bearer $VRCATALOG_API_TOKEN" \
  "https://example.ru/vr/catalog/api/integration/product-filters"
```

```json
{
  "filters": [{
    "key": "brand",
    "label": "Бренд",
    "type": "multi_select",
    "options": [{"value": "Regent", "label": "Regent"}],
    "options_paginated": false
  }]
}
```

Пример поиска:

```bash
curl -X POST \
  -H "Authorization: Bearer $VRCATALOG_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"search":"сковорода","filters":{"brand":["Regent"],"property:Диаметр":["24"]},"excluded":[{"code":"000777"}],"page":1,"page_size":50,"sort_by":"name","sort_dir":"asc"}' \
  "https://example.ru/vr/catalog/api/integration/products/search"
```

```json
{
  "items": [{
    "id": 123,
    "code": "000123",
    "article": "93-AL-24",
    "name": "Сковорода 24 см",
    "properties": [{
      "key": "property:Диаметр",
      "label": "Диаметр",
      "value": "24",
      "display_value": "24"
    }]
  }],
  "total": 1,
  "page": 1,
  "page_size": 50,
  "pages": 1
}
```

`page` начинается с 1, `page_size` — от 1 до 500. Поиск выполняется по `code`,
`article` и `name` без учёта регистра. Допустимая сортировка: `id`, `code`,
`article`, `name`; направление — `asc` или `desc`. Значения одного фильтра
объединяются через **OR**, разные фильтры — через **AND**. Неизвестный фильтр,
сортировка или некорректное тело дают 422. Пустая выборка возвращает 200,
`items: []` и `total: 0`.

Главный идентификатор для связи с `SaleItem` — строковый `code`, потому что он
обязателен и уникален в CatalogVR. `article` возвращается дополнительным ключом.
Оба значения передаются строками без числового преобразования, поэтому ведущие
нули сохраняются. Исключения передаются в JSON-массиве `excluded` (до 1000), а не
в URL.

`selection_id` намеренно не хранится: в проекте нет общего Redis, а локальная
память процесса небезопасна при нескольких экземплярах backend. Для больших
наборов backend Sales Journal повторяет одно и то же тело POST-запроса, увеличивая
`page`; это не передаёт тысячи идентификаторов через URL и не требует TTL-хранилища.
После публикации API в Sales Journal необходимо настроить базовый URL CatalogVR и
`VRCATALOG_API_TOKEN`, загрузить метаданные, а затем выполнять POST-поиск страницами.

## Внутреннее API товаров, менеджеров и складских остатков

Каталог является источником названия товара, ответственного менеджера и актуальных остатков по складам для других сервисов. Оба endpoint требуют заголовок `X-Internal-Token`, скрыты из OpenAPI/Swagger и возвращают HTTP 401 при отсутствующем или неверном токене.

Для сервиса «Сроки годности» задаются:

```env
VRCATALOG_INTERNAL_API_URL=https://kvasmix.ru/vr/catalog/api/internal/products/by-articles
VRCATALOG_INTERNAL_API_TOKEN=<то же значение, что INTERNAL_API_TOKEN в catalogvr>
```

Токен передаётся только в заголовке `X-Internal-Token`. Его нельзя помещать в URL или frontend.

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
  "code": "P-1",
  "name": "Товар А",
  "manager_id": null,
  "manager_name": "Иванов Иван",
  "stocks": []
}
```

Массовый запрос (до 1000 позиций):

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  -d '{"articles":["346051"],"include_zero_stock":true,"include_warehouse_stocks":true,"include_section":true}' \
  "https://kvasmix.ru/vr/catalog/api/internal/products/by-articles"
```

```json
{
  "ok": true,
  "items": [
    {
      "article": "346051",
      "found": true,
      "product_id": 15,
      "code": "P-1",
      "name": "Тестовый товар",
      "manager_id": null,
      "manager_name": "Иванова Ирина",
      "section": "Средства для бассейнов",
      "stocks": [
        {"warehouse":"AVIATORS","warehouse_name":"Авиаторов Зал+Склад","quantity":13.0}
      ]
    }
  ]
}
```

Порядок и повторы товаров сохраняются. Идентификатор сопоставляется точным значением с `products.article`; если артикул в импорте пуст, используется точное совпадение с `products.code`. Частичное и регистронезависимое сопоставление не выполняется.

Поле `include_warehouse_stocks` управляет складской детализацией: при `false` или отсутствии флага `stocks` остаётся пустым массивом для совместимости, а при `true` каждый найденный товар получает массив складских остатков. `stocks` содержит не более одной записи на сочетание товара и склада. `warehouse` — код из остатков, `warehouse_name` — каноническое название из `warehouse_settings` в том же виде, как в UI (например, `Авиаторов Зал+Склад`), `quantity` — числовая сумма актуальных строк остатка этого товара на складе. При включённой детализации API добавляет известные склады из `warehouse_settings` с нулевым количеством, если у товара нет строки остатка по такому складу; неизвестный товар возвращается с пустым `stocks`. Закупочные цены и документы движения endpoint не раскрывает.

Поле `include_section` имеет тип `boolean`, по умолчанию равно `false` и означает «Возвращать значение параметра товара „Раздел“». При `true` найденный товар получает nullable-поле `section` — фактическое значение столбца `products.section`, которое отображается в карточке каталога как «Раздел». Значение очищается от HTML, неразрывных и лишних пробелов, но сохраняет исходный регистр и буквы. Если раздел не заполнен или товар не найден, возвращается `section: null`. При `false` поле отсутствует, поэтому прежний контракт клиентов не меняется. Раздел хранится непосредственно в строке товара и читается тем же пакетным SELECT, без дополнительного запроса на товар и без N+1.

Пакет ограничен 1000 идентификаторами. Некорректный JSON, неверный тип `articles`, превышение лимита и некорректные `include_zero_stock` / `include_warehouse_stocks` / `include_section` возвращают HTTP 422. Неизвестный товар не прерывает пакет и возвращается с `found: false`, пустым `stocks` и, если раздел был запрошен, `section: null`.

Примеры ошибок:

```json
{"detail":"Неверный внутренний токен"}
```

```json
{"detail":[{"type":"json_invalid","loc":["body",0],"msg":"JSON decode error"}]}
```

Локальная ручная проверка:

```bash
curl -sS -X POST \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  --data '{"articles":["ОКА-27134","10001","НЕИЗВЕСТНЫЙ"],"include_zero_stock":true,"include_warehouse_stocks":true,"include_section":true}' \
  'http://127.0.0.1:8000/api/internal/products/by-articles'
```

Проверка отказа без токена:

```bash
curl -i -X POST \
  -H 'Content-Type: application/json' \
  --data '{"articles":["10001"]}' \
  'http://127.0.0.1:8000/api/internal/products/by-articles'
```

Карточки вместе со столбцом `products.section`, свойства, остатки и справочник складов загружаются фиксированным числом пакетных SQL-запросов; число запросов не растёт с количеством товаров. Столбец `products.section` индексирован в модели БД.

### Текущее хранение менеджера и совместимое развитие

Характеристика «Менеджер» импортируется из XML одновременно в универсальную таблицу `product_properties` и в текстовый столбец `products.manager`. Таблицы сотрудников, внутреннего идентификатора менеджера и внешнего ключа на сотрудника сейчас нет, поэтому API возвращает `manager_id: null`, а ФИО — в `manager_name`. Существующий импорт и модель данных не изменяются.

Если стабильный справочник сотрудников появится в источнике данных, безопасный переход состоит из следующих этапов: создать отдельный справочник с уникальным внешним ID; добавить nullable-связь товара с ним; продолжать заполнять и возвращать текстовое имя; сопоставить исторические записи; начать возвращать ID только для надёжно сопоставленных менеджеров. Это сохраняет совместимость потребителей, которые уже используют `manager_name`.

Каждое успешное или отклонённое по токену обращение записывается в `service_logs` с событием `internal_api_request`: дата и время находятся в `created_at`, а JSON в `message` содержит endpoint, число артикулов, длительность, числа найденных/ненайденных товаров, HTTP-код, флаги `include_zero_stock`, `include_warehouse_stocks`, `include_section`, числа товаров с разделом и без него, число складских строк в ответе, список названий складов и короткую диагностику по складским остаткам. Токен, заголовки и сами артикулы не журналируются.

## Быстрый деплой на VPS

## Уведомления «Акция месяца»

Изменения отображаемого значения «Вид товара» на «Акция месяца» и обратно сохраняются в `product_type_changes`. Журнал хранит снимок артикула и наименования, старое и новое значения, источник, время и статус обработки. Успешно отправленные строки не удаляются, а помечаются обработанными; при ошибке SMTP они остаются для следующей попытки.

Почтовое подключение настраивается в **Настройки → Почта**. SMTP-пароль шифруется ключом, производным от `SECRET_KEY`, и не возвращается через API. Расписание, список получателей, ручной запуск и предпросмотр находятся в **Настройки → Сценарии → Акция месяца**. Сценарий по умолчанию выключен и настроен на 22:00 по московскому времени.

Проверка расписания встроена в существующий фоновый цикл автоматического импорта XML и не создаёт отдельного бесконечного процесса. Сценарий читает только необработанные строки индексированного журнала изменений и после успешной отправки отмечает их обработанными.

Раздел **Сценарии** показывает единый список доступных сценариев. Переключатель в строке сохраняет состояние немедленно, а нажатие на название открывает карточку. Каждая фактическая попытка SMTP-отправки сохраняется независимо от служебных логов в `notification_email_history`: получатели, тема, снимок отправленного HTML, статус, ошибка и длительность. История сортируется от новых записей к старым и поддерживает поиск по получателю и фильтрацию по статусу.

Состояние «Акции месяца» хранится отдельно по нормализованному артикулу в `product_promotion_states`. Первый запуск создаёт исходный snapshot без уведомлений. Событие появляется только при фактическом переходе `false → true` или `true → false`; повторная обработка того же XML идемпотентна. XML-дубли диагностируются по артикулу и коду, а отсутствие «Вида товара» в отдельной записи не стирает последнее подтверждённое значение. Перед отправкой старые накопленные дубли событий сворачиваются до итогового перехода, а строки блокируются транзакцией, чтобы параллельные процессы не отправили одно письмо дважды.

## Устойчивое FTP-подключение

Количество попыток и задержка настраиваются в **Настройки → Общие → Подключение к серверу XML** и хранятся в `xml_server_settings` (по умолчанию 5 попыток с паузой 3 секунды). Повтор выполняется только для временных сетевых ошибок; ошибки авторизации и конфигурации завершают проверку сразу. Каждая попытка сохраняется в отдельной таблице `ftp_connection_logs` и в стандартном журнале сервиса. Исходный код не содержит FTP-хост, логин или пароль по умолчанию.

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
