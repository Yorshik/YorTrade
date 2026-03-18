# YorTrade

Мультиплеерная биржевая игра-бот для **Telegram** и **VK**.
Интерфейс на русском: матч запускается в группе/беседе, а торговля и личная статистика идут в личке у каждого игрока.

<a id="quick-start"></a>
## 🚀 Быстрый старт (2 минуты)

Если нужен самый короткий путь до первой игры:

1. Создай Telegram-бота через `@BotFather` и получи токен.
2. Создай файл `.env` и укажи минимум:

```env
TG_TOKEN=ваш_токен_бота
ADMIN_LOGIN=admin
ADMIN_PASS=сильный_пароль
```

3. Запусти проект:

```bash
docker compose up -d
```

4. Добавь бота в группу, открой матч командой `/start_game`.

Примечание:

- для первого запуска после изменений Dockerfile можно использовать `docker compose up --build -d`;
- если используешь VK, добавь `VK_TOKEN` и `VK_GROUP_ID`.


## Содержание

- [🚀 Быстрый старт (2 минуты)](#quick-start)
- [Что это за проект](#что-это-за-проект)
- [⚙️ Требования](#requirements)
- [Что нужно перед запуском](#что-нужно-перед-запуском)
- [Шаг 1 — установить Docker](#шаг-1--установить-docker)
- [Шаг 2 — создать бота Telegram или настроить VK](#шаг-2--создать-бота-telegram-или-настроить-vk)
- [Шаг 3 — скачать проект](#шаг-3--скачать-проект)
- [Шаг 4 — заполнить `.env`](#шаг-4--заполнить-env)
- [Шаг 5 — запустить YorTrade](#шаг-5--запустить-yortrade)
- [Шаг 6 — остановить YorTrade](#шаг-6--остановить-yortrade)
- [Как играть](#как-играть)
- [Команды](#команды)
- [Настройки матча](#настройки-матча)
- [📈 Как работает рынок](#market)
- [🧩 Архитектура (объяснение)](#architecture-explained)
- [Как это работает под капотом](#как-это-работает-под-капотом)
- [Схема базы данных](#схема-базы-данных)
- [Каталоги данных и автозагрузка](#каталоги-данных-и-автозагрузка)
- [🌐 API (если есть)](#api)
- [Конфигурация `.env` (справочник)](#конфигурация-env-справочник)
- [🔐 Безопасность](#security)
- [Запуск без Docker (локально)](#запуск-без-docker-локально)
- [🛠 Частые проблемы](#troubleshooting)
- [Разработка](#разработка)
- [🚧 Roadmap](#roadmap)
- [Навигация по репозиторию](#навигация-по-репозиторию)
- [📄 License](#license)

## Что это за проект

`YorTrade` — это многопользовательская игра-симулятор рынка для чатов.

Позиционирование:

- для игроков: быстрые сессионные матчи, где важны реакция на новости и торговые решения;
- для сообществ: формат «зашли в группу → собрали лобби → сыграли матч»;
- для разработчиков: асинхронный backend с очередями, FSM, runtime-состоянием и воспроизводимой тиковой логикой.

Как проходит матч:

1. Хост создает лобби в группе/беседе.
2. Игроки подключаются.
3. Матч стартует, рынок двигается по тикам.
4. На цены влияют события, новости, инсайды и действия игроков (покупка/продажа).
5. Игра завершается по таймеру или вручную, после чего фиксируется итоговый рейтинг.

Главная идея: общение и управление матчем в групповом чате, а персональный интерфейс (портфель, сделки, баланс, торговые кнопки) у каждого игрока в личке с ботом.

Ключевые фичи:

- одновременная поддержка **Telegram** и **VK**;
- лобби и контроль матча в группе/беседе;
- персональный торговый интерфейс в личке;
- тиковый движок: `event_engine` + `tick_processor` + `GameEngine`;
- рыночные события, новости, инсайды;
- лидерборд, портфель, сделки, достижения;
- очереди RabbitMQ для разделения poller/worker/sender;
- Redis для FSM, дедупликации и rate-limit;
- PostgreSQL как источник истины по игрокам, активам и истории.

<a id="requirements"></a>
## ⚙️ Требования

- Docker Engine + `docker compose`;
- доступ к Telegram (минимум) и/или VK (опционально);
- токены платформ в `.env`;
- для локального запуска без Docker: Python `>=3.10`, PostgreSQL, Redis, RabbitMQ, `uv`.

## Что нужно перед запуском

Для владельца бота:

- компьютер на Linux, macOS или Windows;
- установленный Docker с `docker compose`;
- бот в Telegram;
- бот (сообщество) в VK.

Для игроков:

- достаточно написать боту в личку перед входом в матч.

## Шаг 1 — установить Docker

### Linux (Ubuntu)

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Добавить текущего пользователя в группу `docker`:

```bash
sudo usermod -aG docker $USER
```

После этого перелогинься и проверь:

```bash
docker --version
docker compose version
```

### macOS

1. Установи Docker Desktop: <https://www.docker.com/products/docker-desktop/>
2. Запусти Docker Desktop.
3. Проверь в терминале:

```bash
docker --version
docker compose version
```

### Windows

1. Установи Docker Desktop: <https://www.docker.com/products/docker-desktop/>
2. При установке включи WSL2.
3. Запусти Docker Desktop.
4. Проверь в PowerShell:

```powershell
docker --version
docker compose version
```

## Шаг 2 — создать бота Telegram или настроить VK

### Telegram

1. В Telegram открой `@BotFather`.
2. Выполни `/newbot`.
3. Задай имя и username бота.
4. Сохрани токен (`TG_TOKEN`).

### VK (опционально)

1. Создай сообщество VK или используй существующее.
2. Включи сообщения сообщества.
3. Получи токен сообщества (`VK_TOKEN`) с правами на работу с сообщениями.
4. Узнай ID сообщества (`VK_GROUP_ID`).

Если нужен только Telegram, шаги для VK можно пропустить.

## Шаг 3 — скачать проект

```bash
git clone <URL-репозитория>
cd YorTrade
```

Если работаешь по SSH:

```bash
git clone <SSH-URL-репозитория>
cd YorTrade
```

## Шаг 4 — заполнить `.env`

Создай (или отредактируй) файл `.env` в корне проекта.

### REQUIRED

```env
# REQUIRED: хотя бы одна платформа (TG или VK)
TG_TOKEN=
VK_TOKEN=
VK_GROUP_ID=0

# REQUIRED: bootstrap учетной записи API
ADMIN_LOGIN=admin
ADMIN_PASS=change_me
```

Правила запуска платформ:

- Telegram-клиент поднимется, если заполнен `TG_TOKEN`.
- VK-клиент поднимется, если заполнены `VK_TOKEN` и `VK_GROUP_ID > 0`.
- Можно запускать только одну платформу или обе одновременно.

### OPTIONAL

```env
# Telegram
TG_API_URL=https://api.telegram.org
TG_BOT_USERNAME=

# VK
VK_API_URL=https://api.vk.com/method
VK_API_VERSION=5.199

# Игра
PREFIX=/
MIN_PLAYERS=1

# API
API_AUTH_TTL_HOURS=24

# Инфраструктура (обычно переопределяется docker-compose для app)
DATABASE_DSN=postgresql+asyncpg://postgres:postgres@localhost:5432/app
REDIS_DSN=redis://localhost:6379/0
RABBIT_DSN=amqp://guest:guest@localhost/
```

## Шаг 5 — запустить YorTrade

```bash
docker compose up --build -d
```

Что делает команда:

- поднимает `PostgreSQL`, `Redis`, `RabbitMQ`;
- применяет миграции;
- запускает приложение.

Проверка статуса:

```bash
docker compose ps
```

После запуска добавь бота в группу и начни матч командой `/start_game`.

## Шаг 6 — остановить YorTrade

Остановка сервисов:

```bash
docker compose down
```

Остановка с удалением данных (полный сброс БД/очередей/кэша):

```bash
docker compose down -v
```

Повторный запуск после остановки:

```bash
docker compose up -d
```

## Как играть

1. Добавь бота в группу (Telegram) или беседу (VK).
2. Каждый игрок один раз пишет боту в личку.
3. Хост создает лобби: `/start_game`.
4. Игроки входят в матч: `/join_game`.
5. Хост при необходимости меняет параметры лобби.
6. Хост запускает игру: `/begin_game`.
7. Игроки торгуют в личке: `/game`, `/buy`, `/sell`, кнопки интерфейса.
8. Матч заканчивается по таймеру, вручную (`/stop`, `/end_game`) или при падении числа активных игроков ниже `MIN_PLAYERS`.

## Команды

Префикс по умолчанию: `/`.

### В группе/беседе

| Команда | Назначение |
|---|---|
| `/start_game`, `/start_gameYT` | создать лобби и назначить хоста |
| `/join_game`, `/join_gameYT` | присоединиться к лобби |
| `/begin_game` | запустить матч (только хост) |
| `/stop`, `/end_game` | остановить матч (только хост) |
| `/ping` | проверка доступности бота |

### В личке

| Команда | Назначение |
|---|---|
| `/game`, `/market` | открыть основной экран игры |
| `/buy <asset_id> <amount>` | купить акции |
| `/sell <asset_id> <amount>` | продать акции |
| `/portfolio` | показать портфель |
| `/deals` | показать последние сделки |
| `/leaderboard` | показать лидерборд |
| `/achievements`, `/достижения` | показать достижения |
| `/leave`, `/выйти` | выйти из активной игры |

## Настройки матча

Параметры, которые хост меняет в лобби:

| Параметр | Ключ | По умолчанию | Диапазон |
|---|---|---|---|
| Длительность тика (сек) | `tick_seconds` | `60` | `5..120` |
| Длительность игры (мин) | `game_duration_minutes` | `20` | `5..180` |
| Глобальная волатильность | `global_volatility` | `10.0` | `0.1..50.0` |
| Стартовый баланс | `default_balance` | `1000.0` | `100..1000000` |

Поведение рынка:

- В игру попадают **все компании из `data/data.json`**.
- Стартовая цена каждой компании берется из `data/data.json`.
- При вводе пользовательского значения в настройках бот автоматически возвращает в экран настроек.

<a id="market"></a>
## 📈 Как работает рынок

Рынок обновляется дискретно, по тикам.

1. Тик

- каждый тик — это один цикл расчета цены;
- длительность тика задается `tick_seconds`;
- на каждом тике движок выполняет: планирование драйверов рынка → расчет новых цен → сохранение состояния → обновление UI.

2. Базовые данные

- стартовые цены берутся из `data/data.json`;
- в матче участвуют все компании каталога;
- для каждой компании в runtime ведется история цен.

3. Из чего складывается изменение цены

На тике для каждой компании считается итоговый коэффициент изменения `total_ratio`.
В него входят:

- влияние активных событий (`active_events` + `event_templates`);
- влияние новостей текущего тика;
- влияние инсайдов (истинных и ложных);
- накопленный эффект от заявок игроков (`pending_order_impact`);
- небольшой шум (`NOISE_MIN..NOISE_MAX`).

После суммирования коэффициент ограничивается диапазоном `[-0.1; +0.1]` (не более ±10% за тик).
Новая цена считается как:

`next_price = max(1.0, current_price * (1 + total_ratio))`

4. События и кривая влияния

- события могут длиться несколько тиков;
- сила многотикового события распределяется по кривой `BASE_CURVE = [0.5, 0.8, 1.0, 1.0, 0.8, 0.5]`;
- по завершении тика завершенные события удаляются из active-таблицы;
- в интерфейсе игрокам показывается, сколько тиков осталось до конца события.

5. Влияние игроков на цену

После покупки/продажи в runtime пишется отложенный эффект заявки:

`impact = 15.0 * (amount / shares_total) * direction`

где `direction = +1` для покупки и `-1` для продажи.
Этот процент добавляется в следующий расчет цены компании.

<a id="architecture-explained"></a>
## 🧩 Архитектура (объяснение)

Роли компонентов:

- `Poller`:
  - получает апдейты из Telegram/VK API;
  - кладет их в очередь RabbitMQ (`updates queue`).
- `Worker`:
  - читает апдейты из очереди;
  - прогоняет middleware (maintenance, dedup, user, rate-limit, game-access, callback-sanity);
  - выбирает handler и выполняет бизнес-логику;
  - пишет данные в PostgreSQL/Redis;
  - отправляет исходящие сообщения в `sender queue`.
- `Sender`:
  - читает исходящие задачи;
  - отправляет сообщения/редактирования обратно в Telegram/VK API.

Хранилища и шина:

- `PostgreSQL`:
  - постоянные данные игры (пользователи, игры, портфели, сделки, активы, runtime-таблицы рынка, шаблоны событий, новости, API-auth).
- `Redis`:
  - FSM-состояния, дедупликация, rate-limit и другой быстрый ephemeral-state.
- `RabbitMQ`:
  - буферизация и развязка между приемом апдейтов, обработкой и отправкой ответов.

Отдельно в процессе приложения работает `GameEngine`:

- запускает циклы активных матчей;
- по каждому тикает `event_engine` + `tick_processor`;
- сохраняет runtime и обновляет групповые/личные экраны игроков.

## Как это работает под капотом

### Поток апдейтов (Telegram/VK)

```mermaid
flowchart LR
    platform_api["Telegram / VK API"] --> poller_component["Poller"]
    poller_component --> updates_queue[("RabbitMQ: updates queue")]
    updates_queue --> worker_component["Worker"]
    worker_component --> middleware_chain["Middleware chain"]
    middleware_chain --> handlers["Handlers"]
    handlers --> sender_queue[("RabbitMQ: sender queue")]
    sender_queue --> sender_component["Sender"]
    sender_component --> platform_api

    worker_component --> postgres_db[("PostgreSQL")]
    middleware_chain --> redis_cache[("Redis")]
    handlers --> postgres_db
    handlers --> redis_cache
```

### Цикл матча

```mermaid
flowchart TD
    start_match["/begin_game"] --> init_market["initialize_game_market"]
    init_market --> game_loop["run_game_loop"]
    game_loop --> next_tick["Tick +1"]
    next_tick --> schedule_drivers["event_engine.schedule_market_drivers"]
    schedule_drivers --> process_tick["tick_processor.process_tick"]
    process_tick --> persist_state["save_runtime_state"]
    persist_state --> refresh_ui["refresh_market_message + refresh_private_views"]
    refresh_ui --> finish_check{"Матч завершен?"}
    finish_check -- "нет" --> next_tick
    finish_check -- "да" --> finish_game["finish_game"]
```

GitHub корректно рендерит Mermaid-блоки в Markdown.

## Схема базы данных

```mermaid
erDiagram
    users ||--o{ players : has
    users ||--|| user_achievement_stats : has
    games ||--o{ players : has
    games ||--o{ game_assets : has
    assets ||--o{ game_assets : linked
    players ||--o{ portfolios : owns
    assets ||--o{ portfolios : in
    players ||--o{ deals : makes
    games ||--o{ deals : has
    assets ||--o{ deals : traded

    games ||--|| game_runtime_state : runtime
    games ||--o{ companies : has
    games ||--o{ price_history : has

    event_templates ||--o{ active_events : template
    games ||--o{ active_events : has
    games ||--o{ news : has
    games ||--o{ insider_info : has

    assets ||--o{ phrases : has
    api_auth_users ||--o{ api_auth_sessions : auth
```

## Каталоги данных и автозагрузка

В каталоге `data/` лежат игровые справочники:

- `data/data.json` — компании;
- `data/event_templates.json` — шаблоны событий;
- `data/news.json` — новости;
- `data/pictures/` — изображения для событий/новостей.

При старте приложения данные загружаются автоматически, если таблицы еще пустые.
Если данные уже есть, повторная загрузка пропускается.

<a id="api"></a>
## 🌐 API (если есть)

В проекте есть HTTP API для администрирования и диагностики.

Публичные endpoints:

- `GET /api`
- `GET /api/public`
- `GET /api/health`
- `GET /api/openapi.json`
- `GET /api/docs`
- `GET /api/swagger`

Auth endpoints:

- `POST /api/auth/login`
- `POST /api/auth/logout`

CRUD endpoints (требуют авторизацию):

- `GET /api/tables`
- `GET /api/{table}`
- `GET /api/{table}/{item_id}`
- `POST /api/{table}`
- `PATCH /api/{table}/{item_id}`
- `DELETE /api/{table}/{item_id}`
- `POST /api/{table}/clear`
- `GET /api/delete_user?user_id=...`

Пример логина:

```bash
curl -sS -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"change_me"}'
```

Пример запроса после логина:

```bash
curl -sS http://localhost:8080/api/tables \
  -H "Authorization: Bearer <TOKEN>"
```

## Конфигурация `.env` (справочник)

### REQUIRED

| Переменная | Значение по умолчанию | Зачем нужна |
|---|---|---|
| `TG_TOKEN` | пусто | обязательна для Telegram-клиента |
| `VK_TOKEN` | пусто | обязательна для VK-клиента |
| `VK_GROUP_ID` | `0` | для VK должно быть `> 0` |
| `ADMIN_LOGIN` | `admin` | логин bootstrap-пользователя API |
| `ADMIN_PASS` | `admin` | пароль bootstrap-пользователя API |

### OPTIONAL

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `TG_API_URL` | `https://api.telegram.org` | URL Telegram API |
| `TG_BOT_USERNAME` | пусто | username для deep-link в TG |
| `VK_API_URL` | `https://api.vk.com/method` | URL VK API |
| `VK_API_VERSION` | `5.199` | версия VK API |
| `PREFIX` | `/` | префикс команд |
| `MIN_PLAYERS` | `1` | минимум активных игроков для продолжения матча |
| `API_AUTH_TTL_HOURS` | `24` | TTL API-токена |

### OPTIONAL (инфраструктура)

Эти переменные обычно пробрасываются через `docker-compose.yml` для сервиса `app`,
но нужны для локального запуска без Compose:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_DSN` | `postgresql+asyncpg://postgres:postgres@localhost:5432/app` | подключение к PostgreSQL |
| `REDIS_DSN` | `redis://localhost:6479/0` | подключение к Redis |
| `RABBIT_DSN` | `amqp://guest:guest@localhost/` | подключение к RabbitMQ |

<a id="security"></a>
## 🔐 Безопасность

Минимальные меры перед выкладкой в прод:

1. Обязательно смени `ADMIN_PASS` в `.env` на сильный пароль.
2. Не коммить `.env`, токены и дампы БД в git.
3. При публикации API наружу ограничь доступ (reverse proxy / firewall / VPN).
4. Периодически ротируй `TG_TOKEN` и `VK_TOKEN` при подозрении на утечку.

## Запуск без Docker (локально)

1. Подними инфраструктуру:

```bash
docker compose up -d postgres redis rabbitmq
```

2. Установи зависимости:

```bash
uv sync
```

3. Примени миграции:

```bash
uv run alembic upgrade head
```

4. Укажи в `.env` локальные DSN:

```env
DATABASE_DSN=postgresql+asyncpg://postgres:postgres@localhost:5432/app
REDIS_DSN=redis://localhost:6379/0
RABBIT_DSN=amqp://guest:guest@localhost/
```

5. Запусти приложение:

```bash
uv run python main.py
```

<a id="troubleshooting"></a>
## 🛠 Частые проблемы

1. Контейнеры не стартуют

Проверить статусы:

```bash
docker compose ps
```

Посмотреть логи приложения:

```bash
docker compose logs app
```

2. Бот не отвечает в чате

Проверить, что `app` контейнер запущен и нет ошибок авторизации платформ:

```bash
docker compose ps
docker compose logs app | tail -n 200
```

3. Не поднимается только одна платформа

Проверь значения в `.env`:

- для Telegram нужен `TG_TOKEN`;
- для VK нужны `VK_TOKEN` и `VK_GROUP_ID > 0`.

4. Проблемы с БД/кэшем/очередями

Проверить логи зависимостей:

```bash
docker compose logs postgres
docker compose logs redis
docker compose logs rabbitmq
```

5. Нужен живой поток логов при отладке

```bash
docker compose logs -f app
```

## Разработка

Тесты:

```bash
uv run pytest
```

Линтер:

```bash
uv run ruff check app tests
```

<a id="roadmap"></a>
## 🚧 Roadmap

Планируемые улучшения (черновой список):

- расширить e2e-тесты по сценариям TG/VK;
- добавить метрики и технический health-dashboard;
- улучшить инструменты балансировки рыночных параметров;
- подготовить отдельный гайд по деплою в production.

## Навигация по репозиторию

| Путь | Что здесь |
|---|---|
| `app/clients/` | транспортные клиенты TG/VK: poller, worker, sender, handlers |
| `app/market/` | рыночный движок, модели и обработка тиков |
| `app/utils/` | подготовка игры, лобби, UI, рендер, live-обновления, трейдинг |
| `app/store/` | доступ к PostgreSQL, Redis, RabbitMQ и миграции |
| `app/api/` | HTTP API и авторизация |
| `app/web/` | сборка приложения, конфиг, middleware |
| `data/` | игровые каталоги и картинки |
| `tests/` | тесты |

<a id="license"></a>
## 📄 License
MIT