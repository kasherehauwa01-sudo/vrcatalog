# VR Catalog

VR Catalog — веб-сервис для просмотра товарного каталога, который импортирует данные из XML в базу данных и дальше работает только с БД. Это важно для скорости, фильтрации, экспорта и будущего перехода с SQLite на PostgreSQL.

## Что умеет сервис

- Ручная загрузка XML через кнопку **«Загрузить XML»**.
- Полная замена предыдущего каталога при новом импорте.
- Импорт товаров, кодов, названий, разделов, количества и описаний.
- Импорт любых типов цен без фиксированного списка, например `ЦенаОптовая`, `ЦенаКорпоративная`, `ЦенаРозничная` и будущих новых типов.
- Импорт остатков по каждому складу.
- Импорт всех свойств товара через универсальную таблицу свойств: код свойства, название и значение.
- Импорт изображений, аналогов и штрихкодов.
- Поиск без учета регистра по названию, коду, артикулу, описанию, бренду, производителю, штрихкодам и тегам.
- Автоматическое построение фильтров по данным из базы.
- Детальная карточка товара, избранное, история просмотров, копирование артикула, кода и штрихкодов.
- Экспорт найденных товаров в CSV и Excel.
- Хранение последних 10 импортов как основа для будущего отката и сравнения версий XML.

## Структура проекта

```text
backend/                 FastAPI API, SQLAlchemy, SQLite, Alembic
backend/app/importer/    независимый сервис импорта XML
frontend/                React + TypeScript + Vite + Material UI
deploy/timeweb/          примеры systemd и Nginx для VPS на Timeweb
```

XML читается только модулем `backend/app/importer/xml_importer.py`. После импорта API, поиск, фильтры и экспорт используют таблицы базы данных.

## Локальный запуск

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

API будет доступен по адресу:

```text
http://127.0.0.1:8000/api
```

Swagger-документация:

```text
http://127.0.0.1:8000/docs
```

### Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Если backend запущен локально, в `frontend/.env` укажите:

```env
VITE_API_URL=http://127.0.0.1:8000/api
```

## Переменные окружения

### Backend: `backend/.env`

```env
DATABASE_URL=sqlite:///./vrcatalog.db
APP_NAME=VR Catalog
```

Для Timeweb/VPS удобнее использовать абсолютный путь к SQLite-файлу:

```env
DATABASE_URL=sqlite:////var/www/vrcatalog/backend/vrcatalog.db
APP_NAME=VR Catalog
```

В будущем для PostgreSQL достаточно будет заменить `DATABASE_URL`, например:

```env
DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/vrcatalog
```

### Frontend: `frontend/.env`

```env
VITE_API_URL=https://example.ru/api
```

Замените `example.ru` на домен, подключенный к вашему серверу Timeweb.

## Деплой на Timeweb Cloud/VPS

Инструкция ниже рассчитана на VPS с Ubuntu/Debian, доступом по SSH и доменом, который уже направлен A-записью на IP сервера.

### 1. Подготовить сервер

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nginx nodejs npm
```

Проверьте версии:

```bash
python3 --version
node --version
npm --version
nginx -v
```

### 2. Скопировать проект на сервер

Рекомендуемый путь размещения:

```bash
sudo mkdir -p /var/www/vrcatalog
sudo chown -R $USER:$USER /var/www/vrcatalog
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ> /var/www/vrcatalog
cd /var/www/vrcatalog
```

Если вы загружаете архивом через панель Timeweb, распакуйте проект в `/var/www/vrcatalog`.

### 3. Настроить backend

```bash
cd /var/www/vrcatalog/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Для SQLite в production укажите абсолютный путь:

```env
DATABASE_URL=sqlite:////var/www/vrcatalog/backend/vrcatalog.db
APP_NAME=VR Catalog
```

Проверочный запуск backend:

```bash
cd /var/www/vrcatalog/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте второй SSH-сеанс и проверьте API:

```bash
curl http://127.0.0.1:8000/api/meta
```

После проверки остановите `uvicorn` сочетанием `Ctrl+C`.

### 4. Настроить systemd-сервис backend

В проекте есть пример unit-файла: `deploy/timeweb/vrcatalog.service`.

```bash
sudo cp /var/www/vrcatalog/deploy/timeweb/vrcatalog.service /etc/systemd/system/vrcatalog.service
sudo systemctl daemon-reload
sudo systemctl enable vrcatalog
sudo systemctl start vrcatalog
sudo systemctl status vrcatalog
```

Посмотреть логи backend:

```bash
sudo journalctl -u vrcatalog -f
```

### 5. Собрать frontend

```bash
cd /var/www/vrcatalog/frontend
cp .env.example .env
nano .env
npm install
npm run build
```

В `frontend/.env` должен быть внешний URL API:

```env
VITE_API_URL=https://example.ru/api
```

Для первичной проверки без HTTPS можно временно указать:

```env
VITE_API_URL=http://example.ru/api
```

После изменения `.env` frontend нужно пересобрать:

```bash
npm run build
```

### 6. Настроить Nginx

В проекте есть пример конфига: `deploy/timeweb/nginx.conf`.

Скопируйте его и замените `example.ru` на ваш домен:

```bash
sudo cp /var/www/vrcatalog/deploy/timeweb/nginx.conf /etc/nginx/sites-available/vrcatalog
sudo nano /etc/nginx/sites-available/vrcatalog
sudo ln -s /etc/nginx/sites-available/vrcatalog /etc/nginx/sites-enabled/vrcatalog
sudo nginx -t
sudo systemctl reload nginx
```

Проверьте с сервера:

```bash
curl http://127.0.0.1:8000/api/meta
curl http://example.ru/api/meta
```

Проверьте в браузере:

```text
http://example.ru
```

### 7. Подключить HTTPS

Если на сервере установлен Certbot, выпустите сертификат:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.ru -d www.example.ru
```

После выпуска сертификата обновите `frontend/.env` на HTTPS и пересоберите frontend:

```bash
cd /var/www/vrcatalog/frontend
nano .env
npm run build
```

### 8. Обновление проекта на сервере

```bash
cd /var/www/vrcatalog
git pull
cd backend
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart vrcatalog
cd ../frontend
npm install
npm run build
sudo systemctl reload nginx
```

### 9. Резервное копирование SQLite

Перед крупным импортом или обновлением сделайте копию базы:

```bash
sudo systemctl stop vrcatalog
cp /var/www/vrcatalog/backend/vrcatalog.db /var/www/vrcatalog/backend/vrcatalog.db.backup.$(date +%F-%H%M)
sudo systemctl start vrcatalog
```

## Важные настройки для больших XML

В `deploy/timeweb/nginx.conf` уже указан параметр:

```nginx
client_max_body_size 200m;
```

Если XML-файлы больше 200 МБ, увеличьте значение, например до `500m`, затем проверьте и перезагрузите Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Проверка после деплоя

1. Откройте главную страницу сайта.
2. Нажмите **«Загрузить XML»**.
3. Дождитесь завершения загрузки и импорта.
4. Проверьте, что отображаются:
   - дата последней загрузки;
   - количество товаров;
   - карточки товаров;
   - фильтры;
   - детальная карточка товара;
   - экспорт CSV и Excel.
5. Проверьте API:

```bash
curl https://example.ru/api/meta
curl "https://example.ru/api/products?search=тест"
```

## Частые проблемы

### 413 Request Entity Too Large

Увеличьте `client_max_body_size` в Nginx-конфиге и перезагрузите Nginx.

### Frontend не видит backend

Проверьте `VITE_API_URL` в `frontend/.env`. После изменения этой переменной обязательно выполните `npm run build`.

### Backend не стартует

Проверьте логи:

```bash
sudo journalctl -u vrcatalog -n 100 --no-pager
```

Чаще всего причина в неправильном пути `DATABASE_URL`, отсутствующей виртуальной среде или правах на каталог `/var/www/vrcatalog/backend`.

### Нет прав на SQLite-файл

Дайте пользователю сервиса права на каталог backend:

```bash
sudo chown -R www-data:www-data /var/www/vrcatalog/backend
sudo systemctl restart vrcatalog
```

## Команды разработки

```bash
python -m compileall backend/app backend/alembic
```

```bash
cd frontend
npm run build
```
