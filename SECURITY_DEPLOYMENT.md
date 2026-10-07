# Безопасное развёртывание VR Catalog

## Обязательные переменные

Production должен использовать `ENVIRONMENT=production`, `ENABLE_API_DOCS=false`,
`CORS_ORIGINS=https://kvasmix.ru` и случайные значения длиной не менее 32 символов
для `SECRET_KEY` и `INTERNAL_API_TOKEN`. Также обязательны `ADMIN_PASSWORD_HASH`,
`POSTGRES_PASSWORD` и согласованный с ним `DATABASE_URL`.

Argon2id hash создаётся интерактивно, без помещения пароля в shell history:

```bash
docker compose run --rm --no-deps backend python -c 'from getpass import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass("Admin password: ")))'
```

Результат следует вручную поместить в `ADMIN_PASSWORD_HASH` внутри production `.env`
в одинарных кавычках, чтобы символы `$` Argon2 hash не интерпретировались Compose.

## Порядок deployment и ротации

```bash
cd /path/to/vrcatalog
git pull --ff-only
chmod 600 .env
chown root:root .env
docker compose build --pull
docker compose up -d
docker compose exec backend alembic current
docker compose ps
curl --fail https://kvasmix.ru/vr/catalog/api/health
```

После развёртывания администратор должен вручную:

1. Проверить вход и выход администратора.
2. Заменить скомпрометированный `INTERNAL_API_TOKEN` и синхронно обновить Sales Journal.
3. Сменить FTP-пароль и повторно сохранить его в защищённых настройках.
4. Сменить пароль PostgreSQL и одновременно обновить `DATABASE_URL`.
5. Для ротации `SECRET_KEY` временно задать старый ключ как `PREVIOUS_SECRET_KEY`,
   новый — как `SECRET_KEY`, перезапустить приложение и повторно сохранить SMTP/FTP
   пароли, чтобы они зашифровались новым ключом. После проверки удалить
   `PREVIOUS_SECRET_KEY` и снова пересоздать backend.
6. Ещё раз выполнить `chmod 600 .env` и smoke tests.

Нельзя автоматически менять production-пароли, токены или ключи: внешние клиенты
и зашифрованные SMTP/FTP credentials должны быть синхронизированы администратором.
