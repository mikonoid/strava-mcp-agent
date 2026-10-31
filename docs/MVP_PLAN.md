# MVP: hosted web app

Мета — запустити дашборд як публічний веб-застосунок: юзер заходить на сайт, тисне **Connect with Strava** і отримує графіки та AI-аналіз. Жодних ключів від юзера не потрібно, а витрати на AI жорстко обмежені.

Трекінг задач: GitHub milestone **MVP (hosted)**.

## Прийняті рішення

| Тема | Рішення |
|---|---|
| Хостинг | **Fly.io** (Docker, той самий `Dockerfile`) |
| База даних | **Neon Postgres** (free tier) |
| Джерела даних | **Тільки Strava**. Garmin — після MVP і лише через офіційний Garmin Health API |
| AI-модель (безкоштовний тариф) | **Claude Haiku 5.5** (`claude-haiku-5-5`), ≈ $0.001 за запит |
| Квота AI на юзера | **1 запит на день, 10 на місяць** |
| Глобальний бюджет AI | **$20 на місяць**. Після цього AI вимикається до кінця місяця |
| Свій ключ (BYOK) | **Так**: юзер може вставити свій ключ Anthropic або OpenAI. Тоді квоти не діють, витрати не враховуються в бюджеті |
| Локальний режим | Залишається (`APP_MODE=local`, як зараз) разом з MCP-сервером. Хостинговий режим вмикається через `APP_MODE=hosted` |

## Обсяг MVP

**Входить:**
- Логін через Strava OAuth (акаунт = атлет Strava), вихід з акаунта, видалення акаунта.
- Синхронізація активностей: первинне завантаження за 132 дні, далі оновлення через Strava webhooks.
- Дашборд, як зараз (Form/Fitness/Fatigue, навантаження, тижневий обсяг, активності, сторінка тренування). Дані читаються з БД, а не напряму з API.
- AI-коуч: готові кнопки плюс коротке питання (до 300 символів), квоти, бюджет, кеш, згода на передачу даних.
- BYOK: збереження зашифрованого ключа юзера.
- Privacy Policy, Terms, брендинг «Powered by Strava».
- Деплой на Fly.io з GitHub Actions, моніторинг помилок, проста адмін-сторінка використання.

**Не входить (після MVP):** Garmin, оплата або підписки, вільний чат з інструментами, мобільний застосунок, кілька мов інтерфейсу, порівняння з друзями.

## Архітектура

```
Browser ──HTTPS──▶ Fly.io app (FastAPI, APP_MODE=hosted)
                    ├── web: сторінки, OAuth, API, AI
                    └── worker: синхронізація зі Strava (черга в Postgres)
                          │
Strava ──webhook──▶ /webhooks/strava ──▶ jobs ──▶ Strava API
                          │
                    Neon Postgres ◀── users, tokens, activities, ai_requests
                          │
                    Anthropic API (Haiku) ◀── тільки зі згоди юзера
```

- **Один процес на старт.** Worker — фоновий цикл у тому самому застосунку. Якщо навантаження зросте, його виносять в окремий Fly process group.
- **Черга задач у Postgres** (`jobs` + `SELECT … FOR UPDATE SKIP LOCKED`) замість Redis, щоб не було ще одного сервісу.
- **Сесії** у підписаній cookie: `HttpOnly`, `Secure`, `SameSite=Lax`. Наявна перевірка Origin для POST залишається.
- **Шифрування токенів** (Strava refresh/access, ключі BYOK): Fernet, ключ у `ENCRYPTION_KEY` (Fly secret).
- **ORM і міграції:** SQLAlchemy 2 + Alembic.

### Модель даних (чернетка)

| Таблиця | Поля |
|---|---|
| `users` | id, strava_athlete_id (unique), name, avatar_url, created_at, last_login_at, ai_consent_at, is_admin |
| `strava_tokens` | user_id, access_token_enc, refresh_token_enc, expires_at, scope |
| `activities` | id (Strava id), user_id, start_date_local, sport_type, name, distance_m, moving_time_s, elevation_gain_m, avg_hr, max_hr, updated_at |
| `activity_details` | activity_id, splits_json, laps_json, fetched_at (кеш для сторінки тренування) |
| `jobs` | id, kind (initial_sync / activity_upsert / activity_delete / deauthorize), payload, status, attempts, run_after |
| `ai_requests` | id, user_id, created_at, kind, question_hash, model, input_tokens, output_tokens, cost_usd, byok, cached, status, response_md |
| `user_api_keys` | user_id, provider, key_enc, created_at |

## Контроль витрат на AI

Захист у кілька шарів, від найжорсткішого:

1. **Spend limit в Anthropic Console** — $25 на місяць. Це запобіжник на випадок багу в коді.
2. **Глобальний бюджет $20 на місяць.** Сума `cost_usd` за поточний місяць з `ai_requests`. Перед викликом робиться *резервування* за песимістичною оцінкою вартості, щоб паралельні запити не перевищили бюджет. Після відповіді резерв замінюється фактичною вартістю.
3. **Квота юзера: 1 запит на день і 10 на місяць** (UTC). У UI показується «Залишилось: 1 сьогодні · 7 цього місяця».
4. **Обмеження розміру:** `max_tokens=1200`. Вхід стискається до ≈ 4–6 тис. токенів (агрегати, а не сирі дані). Питання не довше 300 символів.
5. **Кеш:** той самий `kind` і питання на тих самих даних того ж дня віддаються з БД без виклику LLM і квоту не витрачають.
6. **Rate limit:** не більше 5 AI-запитів на хвилину з одного IP. Окремо глобальний ліміт паралельних викликів LLM (наприклад, 3).
7. **Алерти:** при 50% і 80% бюджету — подія в Sentry і лист адміну. При 100% AI вимикається, а в UI з'являється пропозиція використати свій ключ.

**Вартість за таблицею цін у коді** (оновлюється вручну):

| Модель | Вхід за 1 млн токенів | Вихід за 1 млн токенів | ≈ за запит (5k вхід / 1.2k вихід) |
|---|---|---|---|
| claude-haiku-5-5 | $0.10 | $0.50 | ≈ $0.0011 |

Найгірший сценарій: 1000 активних юзерів × 10 запитів = 10 000 запитів ≈ **$11 на місяць**, тобто в межах бюджету.

**BYOK:**
- ключ шифрується (Fernet), ніколи не логуюється і не показується повністю (тільки `sk-…abcd`);
- під час збереження ключ перевіряється одним мінімальним запитом;
- з BYOK квоти й бюджет не діють, але rate limit залишається;
- юзер може видалити ключ у будь-який момент.

## Strava: вимоги і комплаєнс

- [ ] Окремий **production Strava app** з callback domain = домен сервісу.
- [ ] **Заявка на розширення athlete capacity.** Новий застосунок обмежений 1 атлетом. Подати якомога раніше: потрібні скріншоти, опис, Privacy Policy.
- [ ] **Webhooks** (`/webhooks/strava`): `create`/`update`/`delete` для активностей, `deauthorize` для атлета, щоб видалити його дані.
- [ ] **Ліміти API** (≈ 200 за 15 хв і 2000 на день на застосунок). Тому лише webhooks, черга з backoff і дані з БД. При 429 задача відкладається до наступного вікна.
- [ ] **Згода на AI.** Згідно з [Strava API Agreement](https://www.strava.com/legal/api) передача даних третім сторонам (LLM-провайдеру) можлива лише з явної згоди юзера. Тому перед першим AI-запитом юзер окремо ставить галочку, а відкликати згоду можна в акаунті.
- [ ] Дані юзера показуються лише йому самому.
- [ ] Брендинг: «Powered by Strava», кнопка Connect за [гайдлайнами](https://developers.strava.com/guidelines/), посилання «View on Strava».
- [ ] Перевірити Developer Guidelines щодо використання даних з AI.

## Безпека і приватність

- Секрети тільки у Fly secrets: `DATABASE_URL`, `SESSION_SECRET`, `ENCRYPTION_KEY`, `STRAVA_CLIENT_ID/SECRET`, `STRAVA_WEBHOOK_VERIFY_TOKEN`, `ANTHROPIC_API_KEY`, `SENTRY_DSN`.
- У hosted-режимі немає сторінки Settings із серверними секретами. Є лише сторінка «Account»: згода на AI, свій ключ, видалення акаунта.
- «Delete account» видаляє юзера, токени, активності, AI-історію і ключі, а також викликає Strava deauthorize.
- Логи без токенів, ключів і відповідей LLM.
- `TrustedHostMiddleware` налаштований на домен сервісу, примусовий HTTPS, HSTS.

## Інфраструктура (Fly.io)

- `fly.toml`: 1 machine `shared-cpu-1x` на 512 МБ, `auto_stop_machines = "off"` (worker має працювати), health check `/healthz`.
- Neon: проєкт у регіоні поруч із Fly (наприклад, обидва в Frankfurt), pooled connection string. Бекапи — Neon PITR.
- Міграції: `alembic upgrade head` як `release_command` у `fly.toml`.
- CI/CD: GitHub Actions — тести на PR, `flyctl deploy` при push у `main`.
- Моніторинг: Sentry (free tier), Fly metrics, адмін-сторінка `/admin` (юзери, AI-витрати за день і місяць, помилки синхронізації).
- Домен: власний або `*.fly.dev` на старті.

**Орієнтовна вартість на місяць:**

| Що | $ |
|---|---|
| Fly.io (1 machine 512 МБ) | ≈ 3–5 |
| Neon Postgres | 0 (free tier) |
| Sentry | 0 (free tier) |
| Домен | ≈ 1 |
| AI (Haiku, жорсткий ліміт) | ≤ 20 |
| **Разом** | **≤ ≈ 26** |

## Етапи

| # | Етап | Оцінка | Issue |
|---|---|---|---|
| 0 | Підготовка: Strava prod app і заявка на athlete capacity, Neon, Fly, Anthropic spend limit, домен | 0.5 дня + очікування Strava | [#1](https://github.com/mikonoid/strava-mcp-agent/issues/1) |
| 1 | БД: SQLAlchemy, Alembic, моделі, `APP_MODE` | 1 день | [#2](https://github.com/mikonoid/strava-mcp-agent/issues/2) |
| 2 | Логін через Strava, сесії, logout, сторінка «Account» | 1 день | [#3](https://github.com/mikonoid/strava-mcp-agent/issues/3) |
| 3 | Per-user Strava client зі збереженням оновлених токенів | 0.5 дня | [#4](https://github.com/mikonoid/strava-mcp-agent/issues/4) |
| 4 | Синхронізація: черга jobs, первинний імпорт, webhooks, deauthorize | 2 дні | [#5](https://github.com/mikonoid/strava-mcp-agent/issues/5) |
| 5 | Дашборд і сторінка тренування читають з БД | 1 день | [#6](https://github.com/mikonoid/strava-mcp-agent/issues/6) |
| 6 | AI: квоти, бюджет, резервування, кеш, згода, Haiku | 1.5 дня | [#7](https://github.com/mikonoid/strava-mcp-agent/issues/7) |
| 7 | BYOK | 0.5 дня | [#8](https://github.com/mikonoid/strava-mcp-agent/issues/8) |
| 8 | Видалення акаунта і даних | 0.5 дня | [#9](https://github.com/mikonoid/strava-mcp-agent/issues/9) |
| 9 | Privacy Policy, Terms, брендинг Strava | 0.5 дня | [#10](https://github.com/mikonoid/strava-mcp-agent/issues/10) |
| 10 | Деплой: `fly.toml`, CI/CD, secrets, health check, Sentry | 1 день | [#11](https://github.com/mikonoid/strava-mcp-agent/issues/11) |
| 11 | Адмін-сторінка використання і алерти бюджету | 0.5 дня | [#12](https://github.com/mikonoid/strava-mcp-agent/issues/12) |
| 12 | Тести (квоти, бюджет, webhooks, аналітика) і smoke-тест на проді | 1 день | [#13](https://github.com/mikonoid/strava-mcp-agent/issues/13) |

**Разом ≈ 11–12 робочих днів.** Етап 0 треба почати першим, бо розгляд заявки в Strava може тривати.

## Definition of Done

- Новий юзер заходить на сайт → Connect with Strava → бачить дашборд зі своїми даними протягом 1–2 хвилин.
- Нова активність у Strava з'являється в дашборді протягом кількох хвилин (через webhook).
- AI без згоди не працює. Зі згодою — не більше 1 запиту на день і 10 на місяць. При вичерпаному бюджеті з'являється зрозуміле повідомлення і пропозиція використати свій ключ.
- Сумарні витрати на AI не можуть перевищити $20 на місяць (перевірено тестом на конкурентні запити).
- Deauthorize у Strava або «Delete account» повністю видаляє дані юзера.
- Секретів немає ні в репозиторії, ні в логах. Сервіс працює лише по HTTPS.

## Ризики

| Ризик | Що робимо |
|---|---|
| Strava довго розглядає або відхиляє заявку на athlete capacity | Подати на етапі 0. До схвалення — закрита бета (ви + тест-акаунти) |
| Ліміти Strava API при первинному імпорті багатьох юзерів | Черга з backoff, імпорт у кілька кроків, обмеження нових реєстрацій на день |
| Зловживання AI (боти, мульти-акаунти) | Квоти на акаунт Strava, rate limit на IP, глобальний бюджет, spend limit у консолі |
| Зміна цін або назв моделей | Модель і ціни в конфігу, алерт при помилці API |
| Витік токенів | Шифрування, мінімальні scope, ротація `ENCRYPTION_KEY` описана в runbook |
