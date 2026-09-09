# Premium B2B Mailer

Multi-tenant SaaS для B2B outreach: контакты, продуктовые направления, TipTap-шаблоны,
цепочки, кампании, SMTP/SES-отправка, tracking и интеграции Bitrix24, Hunter,
LinkedIn Sales Navigator/Marketing API и Tenchat.

Phase 3 добавляет A/B-тесты с frequentist/Bayesian-анализом, валидацию и enrichment
контактов, дневные продуктовые метрики и отчёты, управление SPF/DKIM/DMARC,
автоматический прогрев, ежедневный DNSBL-мониторинг и проверку качества писем в редакторе.

Phase 4 добавляет персональные in-app/email/Web Push уведомления с WebSocket-доставкой,
tenant-scoped журнал аудита и CSV/PDF-экспорт, подписанные HMAC-SHA256 исходящие webhooks с
защитой от SSRF и пятью попытками доставки, а также тарифы, usage metering, счета и платежи
через ЮKassa, Stripe и Tinkoff Kassa.

## Контакты, шаблоны и CTA в Studio

1. Откройте Studio, войдите (или зарегистрируйтесь) и выберите рабочее пространство.
2. В разделе **Контакты и импорт** выберите Excel `.xlsx` или `.csv` (до 10 МБ,
   5000 строк, 100 колонок). Старые `.xls` предварительно сохраните как `.xlsx`.
   Выберите лист Excel и строку заголовков. CSV распознаёт UTF-8 / Windows-1251,
   запятую / точку с запятой / табуляцию и строку Excel `sep=;`.
3. Проверьте автоматическое сопоставление колонок: email, Ф.И.О. руководителя,
   имя/фамилия/отчество по отдельности, организация, должность, телефон, сайт,
   отрасль, размер компании, выручка, теги. Для дополнительных колонок задайте
   латинское имя переменной (например `city`, `inn`). Не назначенные колонки
   **не сохраняются**. Числовые идентификаторы с ведущими нулями храните в Excel как текст.
4. Проверьте первые пять записей и отчёт ошибок, затем нажмите **Импортировать**.
   Некорректные строки и дубли внутри файла пропускаются; существующие контакты
   не перезаписываются. Применяются лимиты текущего серверного тарифа. Импорт не отправляет писем.
5. В разделе **Шаблоны писем** создавайте, находите, редактируйте, копируйте и удаляйте
   шаблоны. В редакторе задайте название, тему и стадию: первое обращение, повторное,
   прогрев, предложение/CTA или напоминание. Нажмите **Сохранить шаблон** — запись и
   её версия сохраняются в базе рабочего пространства. Категория описывает назначение;
   существующие шаги цепочек (`template_id`) не переназначаются автоматически.
6. В базе нажмите **Подставить в письмо**. Добавляйте переменные `{{full_name}}`,
   `{{company}}`, `{{city}}` и другие через поле «Переменная». Все встроенные поля и
   `custom_fields` доступны также серверному формированию писем и текстовым шагам цепочки.
7. Нажмите **+ CTA**, задайте видимый текст и полный URL. Чтобы изменить CTA,
   выделите кнопку в редакторе и снова нажмите **+ CTA**. В **Проверить письмо**
   появляется HTML-предпросмотр: ссылка кликабельна, адрес скрыт за текстом кнопки.
   Недостающие переменные помечаются. HTML можно скачать. Plain-text вариант
   сохраняет адрес открыто, поскольку скрытые ссылки в нём не поддерживаются.

Проверки интерфейса: `cd frontend && pnpm test && pnpm test:e2e && pnpm build`.
Браузерные тесты используют синтетические данные и API-заглушки, не запускают рассылку.
Серверные тесты персонализации: `pytest tests/test_import_personalization.py`.

## Быстрый запуск окружения

Требования: Docker Engine с Compose v2.

```bash
docker compose up --build
```

После запуска:

- UI: <http://localhost:8080>
- API docs: <http://localhost:8000/docs>
- API health: <http://localhost:8000/health>
- MinIO console: <http://localhost:9001> (`minioadmin` / `minioadmin`)

Compose автоматически ждёт health checks, создаёт bucket `mailer`, применяет Alembic отдельным
`migrate`-контейнером под DB owner и запускает API/Celery под ролью `mailer_app` без DDL/trigger
privileges. Для реальной отправки задайте `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`DEFAULT_SENDER_DOMAIN` и безопасный `APP_SECRET_KEY` через `.env`; полный список находится в
[.env.example](.env.example).

## Production deployment

Рабочая схема разделена на два окружения:

- frontend: <https://premium-b2b-mailer.vercel.app>;
- API: Vercel rewrite `/api/*` → `https://5.129.234.72/mailer/api/*`;
- backend stack: `/opt/premium-b2b-mailer` на NL-server;
- PostgreSQL, Redis, MinIO и Mailpit доступны только внутри Docker network;
- наружу опубликован только API через существующий TLS reverse proxy.

### Общий HTTPS-прокси: восстановление 9 сентября 2026

Прокси `tiktokbot-nginx-1` использует `/opt/tiktokbot/nginx.conf` и основной
`/opt/tiktokbot/docker-compose.yml`. В основном compose закреплены read-only mounts
`/etc/letsencrypt` и `/var/www/certbot`: одного дополнительного override-файла
недостаточно, если следующее развёртывание запускается только с основным compose.

Существующие HTTP-маршруты сохранены. Добавлены HTTP-01 challenge location
`/.well-known/acme-challenge/` с root `/var/www/certbot` и отдельный TLS server на 443
для `5.129.234.72`, проксирующий `/mailer/` в `premium-b2b-mailer-api:8000`.
Используется Docker DNS resolver `127.0.0.11`, чтобы пересоздание API не ломало адресацию.
Проверка соединения с фронтендом: `https://premium-b2b-mailer.vercel.app/backend-health`.

Рабочий клиент IP-сертификатов — `/opt/certbot-venv/bin/certbot` (5.7.0),
плановое продление выполняет `certbot-ip-renew.timer`. Старый `/usr/bin/certbot`
(2.9.0) не подходит для IP-сертификатов. Проверять продление следует командой:

```bash
/opt/certbot-venv/bin/certbot renew --cert-name 5.129.234.72 --dry-run --no-random-sleep-on-renew --run-deploy-hooks
```

Существующий hook `/usr/local/sbin/reload-tiktokbot-nginx` проверяет конфигурацию
и перезагружает Nginx после обновления сертификата. Проверка prod API, скрытого CTA,
HTTP health другого приложения и тест продления прошли. Резервные копии обоих
исходных файлов прокси: `/opt/tiktokbot/backups/mailer-https-20260909/`.

Первичное развёртывание на сервере:

```bash
cd /opt/premium-b2b-mailer
./infrastructure/production/bootstrap-env.sh .env
docker compose --env-file .env -f docker-compose.production.yml pull
docker compose --env-file .env -f docker-compose.production.yml up -d --build
```

`bootstrap-env.sh` создаёт `.env` с правами `0600` и случайными production-секретами, не
перезаписывая существующий файл. По умолчанию SMTP направлен в закрытый Mailpit, поэтому весь
email pipeline работает без отправки сообщений реальным адресатам. Для реальной доставки замените
`SMTP_*`/`DEFAULT_SENDER_DOMAIN` либо включите SES в серверном `.env` и перезапустите API/worker.
Ключи внешних CRM, enrichment и платёжных провайдеров также задаются только в серверном `.env`.

## Первый сценарий API

1. `POST /api/v1/auth/register` и `POST /api/v1/auth/login`.
2. Передавайте access token как `Authorization: Bearer ...`.
3. Создайте workspace через `POST /api/v1/workspaces`.
4. Для tenant endpoints передавайте `X-Workspace-ID`.
5. Загрузите шесть направлений через `POST /api/v1/products/seed/defaults`.
6. Создайте templates, sequence и campaign; перед start проверьте `GET /api/v1/sequences/{id}/validate`.

## Локальная разработка

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Проверки:

```bash
make test
make test-phase3-coverage
make test-phase4
make test-phase4-coverage
make lint
cd frontend && npm run build
```

## Архитектура

Каждый bounded context в `app/modules` разделён на SQLAlchemy models, Pydantic schemas, repository, service, router, events/tasks и exceptions. Все выборки бизнес-сущностей ограничены `workspace_id`, полученным из проверенного membership. Refresh tokens хранятся как digest, ротируются по `family_id`; reuse отзывает всю семью.

Scheduler блокирует due-строки через `FOR UPDATE SKIP LOCKED`, поэтому несколько workers могут безопасно разбирать очередь. SMTP формирует `multipart/alternative`, List-Unsubscribe и tracking pixel. Redis содержит Celery broker/result backend и event bus; MinIO предоставляет S3-compatible storage для CSV/XLSX.

Phase 4 события публикуются в `events:<event.type>` и обрабатываются уведомлениями,
аудитом, webhooks и биллингом. Audit и billing фиксируются в исходной транзакции, затем durable
enterprise outbox после commit материализует webhook deliveries и отдельные durable jobs для
каждого email/Web Push/Telegram-канала. Успешные каналы не повторяются при сбое соседнего;
delivery row UUID стабилен между попытками и используется как Message-ID для email и delivery_id
в Web Push payload. Внешняя доставка имеет семантику at-least-once (Telegram не предоставляет
idempotency API), поэтому получатели webhook/push должны дедуплицировать стабильный ID. Redis
pub/sub — только best-effort realtime-ускорение и не определяет завершённость outbox. Enterprise
event получает `dispatched_at` только когда все durable notification/webhook deliveries успешны;
partial failure оставляет событие незавершённым для последующей сверки.
Legacy `send_notification` Celery entrypoint удалён: зарегистрированные notification tasks не
могут отправлять внешние каналы в обход `notification_deliveries` и commit boundary.
Ошибка обязательной audit-записи откатывает бизнес-транзакцию без Redis/email/push/webhook side effects; PostgreSQL
triggers запрещают UPDATE/DELETE/TRUNCATE журналов. Realtime-клиент подключается к
`/api/v1/notifications/ws?workspace_id=<uuid>` с access token в `Authorization: Bearer`,
HttpOnly cookie `access_token` либо двумя WebSocket subprotocol elements: `bearer, <JWT>`;
сервер выбирает только `bearer` и никогда не отражает JWT. Cookie-аутентификация дополнительно
требует `Origin` из `CORS_ORIGINS`. Секрет исходящего webhook
показывается только при создании, хранится зашифрованным и используется для заголовка
`X-Webhook-Signature: sha256=...`. Повторная доставка имеет тот же `X-Webhook-Id`, что позволяет
получателю реализовать идемпотентность. Delivery сначала фиксируется в transaction outbox, и
только после commit передаётся Celery; DNS-адрес проверяется повторно и закрепляется за соединением,
redirects отключены.

Неуспешные login/lockout/MFA/refresh-reuse/refresh-expiry пишутся отдельной транзакцией в
append-only `security_audit_events`. Email хранится только как HMAC-SHA256, а password, MFA code и
refresh/access tokens в событие не передаются.

Тариф создаётся лениво как Free. Лимиты проверяются до отправки письма, создания контактов,
добавления домена и принятия участника в workspace. Платёжные callback’и идемпотентны: Stripe
проверяется по webhook signature, ЮKassa повторно запрашивается через API, Tinkoff проверяется по
Token; сумма и валюта сверяются со счётом перед активацией тарифа. Каждый paid subscribe требует
стабильный `Idempotency-Key` в header или body: ключ уникален внутри workspace, сохраняется в
invoice. Провайдер получает отдельный HMAC-derived ключ, включающий workspace, provider и
операцию (для Tinkoff — как `OrderId`), поэтому одинаковые клиентские ключи разных tenants не
могут разделить checkout. Provider payment/invoice identities уникальны вместе с provider.
Stripe Checkout создаёт recurring subscription, а каждое подтверждённое `invoice.paid` создаёт
локальный renewal invoice. ЮKassa и Tinkoff работают как ручное продление: `auto_renew=false`,
период не сдвигается без подтверждённой оплаты.

Омниканальный scheduler исполняет шаги `email`, `tenchat_message` и
`linkedin_message`. Для Tenchat/LinkedIn без доступного профиля выполняется fallback в email;
публичного LinkedIn API для cold outreach нет, поэтому LinkedIn message также безопасно уходит в
email fallback. Ответ, полученный через Bitrix24 или Tenchat, помечает контакт как replied и
останавливает активные цепочки.

Для SES задайте `EMAIL_PROVIDER=ses`, AWS credentials/role и обязательный `SES_SNS_TOPIC_ARN`.
Единственный ingress — `/api/v1/ses/webhook`; SNS-конверт и точный topic криптографически
проверяются до обработки bounce/complaint. Все внешние клиенты используют
exponential backoff, rate limits, circuit breakers и не логируют токены/API keys.

`make test` проверяет порог 80% для критической service-layer поверхности: auth, contacts, sender, scheduler и security. Полный API integration прогон выполняется тем же pytest-набором; DB-зависимые сценарии следует запускать рядом с PostgreSQL из Compose.

## Production checklist

- Заменить локальные секреты и ограничить CORS реальным доменом.
- Настроить SPF, DKIM и DMARC для sender domains.
- Ограничить security group и ingress для `/api/v1/ses/webhook`; подпись SNS уже проверяется.
- Добавить sender domains через `/api/v1/domains`, опубликовать выданные DNS-записи и дождаться
  статуса `verified` до production-рассылки.
- Задать `NEVERBOUNCE_API_KEY`, если требуется второй внешний fallback после Hunter; без ключей
  syntax/MX/disposable/role-based проверки продолжают работать локально.
- Использовать managed PostgreSQL/Redis/S3, backup и observability.
- Хранить `POSTGRES_OWNER_PASSWORD` отдельно от `POSTGRES_RUNTIME_PASSWORD`; owner URL передавать
  только migration job. Для существующего локального volume после перехода на разделённые роли
  создайте роли вручную либо пересоздайте только development volume после резервного копирования.
- Задать VAPID-ключи для Web Push и платёжные ключи только через secret manager/environment;
  не включать `WEBHOOK_ALLOW_PRIVATE_URLS` вне изолированной локальной разработки.
- Выполнить нагрузочное тестирование на целевой инфраструктуре; заявленные 1000 писем/мин требуют множества sender domains из-за лимита 50/час на домен.
