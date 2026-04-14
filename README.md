# n8n + FastAPI + PostgreSQL Stack

Production-ready orchestration stack:
- **n8n** — visual workflow orchestrator (self-hosted)
- **FastAPI** — async Python API for complex business logic
- **PostgreSQL** — shared database (separate DB per service)
- **Nginx** — reverse proxy with SSL (production)

```
┌─────────────────────────────────────────────────────┐
│                      Internet                       │
└───────────────────┬─────────────────────────────────┘
                    │ 80/443
           ┌────────▼────────┐
           │     Nginx       │  reverse proxy + SSL
           └──┬──────────┬───┘
              │          │
     ┌────────▼──┐  ┌────▼──────┐
     │   n8n     │  │  FastAPI  │
     │ :5678     │  │  :8000    │
     └─────┬─────┘  └─────┬─────┘
           │              │
           └──────┬───────┘
                  │
         ┌────────▼────────┐
         │   PostgreSQL    │
         │  n8n_db appdb   │
         └─────────────────┘
```

---

## Quick start — local development

```bash
# 1. Clone and enter
git clone <repo> && cd <repo>

# 2. Setup local env and start
make local-setup          # copies .env.local → .env, then docker compose up -d

# 3. Run migrations
make migrate

# 4. Open
#   n8n    → http://localhost:5678
#   API    → http://localhost:8000
#   Docs   → http://localhost:8000/docs
```

---

## Deployment on VPS

### Prerequisites
- Docker + Docker Compose v2
- Domain with DNS pointing to the VPS
- SSL certificates (Let's Encrypt or your own)

```bash
# 1. Copy and fill production env
cp .env.example .env
nano .env                 # fill in all values

# 2. Place SSL certs
cp fullchain.pem nginx/ssl/api.crt
cp privkey.pem  nginx/ssl/api.key
cp fullchain.pem nginx/ssl/n8n.crt
cp privkey.pem  nginx/ssl/n8n.key

# 3. Update nginx/conf.d/*.conf with your real domain names

# 4. Start in production mode (override file NOT loaded)
make up

# 5. Run migrations
make migrate
```

---

## Make commands

| Command | Description |
|---|---|
| `make local-setup` | Copy `.env.local` → `.env` and start |
| `make local-up` | Start with hot-reload (override loaded) |
| `make local-down` | Stop all services |
| `make local-logs` | Tail all logs |
| `make up` | Start in production mode |
| `make migrate` | Run Alembic migrations |
| `make migrate-create MSG='...'` | Generate new migration |
| `make shell-api` | Bash into the API container |
| `make shell-db` | psql into appdb |
| `make test` | Run pytest suite |
| `make lint` | Ruff lint + format |

---

## Project structure

```
.
├── docker-compose.yml          # Production services
├── docker-compose.override.yml # Local dev overrides (auto-loaded)
├── .env.example                # Template — copy to .env
├── .env.local                  # Ready-to-use local config
├── Makefile                    # Shortcut commands
│
├── nginx/
│   ├── nginx.conf              # Main nginx config
│   └── conf.d/
│       ├── api.conf            # FastAPI vhost
│       └── n8n.conf            # n8n vhost (with WS support)
│
├── postgres/
│   └── init.sql                # Creates n8n + appdb databases
│
└── api/
    ├── Dockerfile              # Production multi-stage build
    ├── Dockerfile.dev          # Development with hot-reload
    ├── pyproject.toml          # Dependencies (Python 3.12)
    ├── alembic.ini
    ├── alembic/
    │   ├── env.py              # Async Alembic config
    │   └── versions/           # Migration files
    └── app/
        ├── main.py             # FastAPI app factory + lifespan
        ├── core/
        │   ├── config.py       # Settings (pydantic-settings)
        │   ├── database.py     # Async SQLAlchemy engine + session
        │   ├── logging.py      # Structured logging (structlog)
        │   └── http_client.py  # Shared httpx client
        ├── models/
        │   ├── base.py         # UUID + timestamp mixins
        │   └── task.py         # Task model
        ├── schemas/
        │   └── task.py         # Pydantic request/response schemas
        ├── services/
        │   ├── task_service.py # Async CRUD for tasks
        │   └── n8n_service.py  # n8n webhook + API client
        └── api/v1/
            ├── router.py
            └── endpoints/
                ├── health.py   # /health + /ping
                └── tasks.py    # Full task CRUD + n8n trigger
```

---

## n8n ↔ API integration patterns

### Pattern 1 — n8n triggers API

In n8n, use an **HTTP Request** node pointing to:
```
POST http://api:8000/api/v1/tasks/
Body: { "name": "my-job", "task_type": "report", "payload": {...} }
```

The API creates the task, processes it asynchronously, and returns `201` immediately.

### Pattern 2 — API triggers n8n

From your Python code, call `N8nService.trigger_webhook()`:
```python
from app.services.n8n_service import N8nService

result = await n8n_service.trigger_webhook("my-workflow", {"data": "..."})
```

### Pattern 3 — n8n polls task status

After creating a task, n8n polls:
```
GET http://api:8000/api/v1/tasks/{task_id}
```
until `status` is `success` or `failed`.

### Pattern 4 — API callbacks n8n

Use n8n's **Webhook** node as a callback URL. Pass it in the task payload and
call it from Python when processing is done.

---

## Adding a new task type

1. Add a handler in [api/app/api/v1/endpoints/tasks.py](api/app/api/v1/endpoints/tasks.py) inside `_process_task()`:

```python
if task_type == "my_new_type":
    result = await my_handler(payload)
```

2. Optionally create a dedicated service in `api/app/services/`.

3. Generate a migration if you added models:
```bash
make migrate-create MSG="add my_new_model"
make migrate
```

---

## Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_USER` | yes | DB superuser |
| `POSTGRES_PASSWORD` | yes | DB password |
| `N8N_DB_NAME` | yes | n8n database name |
| `API_DB_NAME` | yes | API database name |
| `N8N_HOST` | yes | n8n public hostname |
| `N8N_ENCRYPTION_KEY` | yes | n8n secrets key (32+ chars) |
| `N8N_BASIC_AUTH_USER` | yes | n8n login |
| `N8N_BASIC_AUTH_PASSWORD` | yes | n8n password |
| `API_SECRET_KEY` | yes | API JWT/session key |
| `API_ENV` | no | `development` or `production` |
| `LOG_LEVEL` | no | `debug`/`info`/`warning` |
| `TIMEZONE` | no | e.g. `Europe/Paris` |
