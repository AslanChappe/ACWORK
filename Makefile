# ============================================================
# Makefile — shortcuts for common operations
# ============================================================
#
# VIRTUAL ENV (local dev — IDE, linter, tests sans Docker)
#   make venv          — crée .venv dans api/ via uv (ou pip fallback)
#   make install       — installe les dépendances dans le venv
#   make lint-local    — ruff depuis le venv (pas besoin de Docker)
#   make test-local    — pytest avec SQLite, sans Docker
#
# DOCKER (stack complète)
#   make local-setup   — copie .env.local → .env + docker compose up
#   make local-up / local-down / local-logs
#   make migrate / migrate-create MSG='...'
#   make shell-api / shell-db / shell-redis
#
# CELERY
#   make worker-logs   — logs du worker en temps réel
#   make worker-restart — redémarrer le worker (après modif de tasks.py)
#   make beat-logs     — logs du scheduler
#   make celery-status — état des workers actifs
#   make celery-inspect — tâches en cours d'exécution
#   make flower        — lancer Flower (UI de monitoring Celery)
#
# PRODUCTION VPS
#   make up / down / logs
# ============================================================

.PHONY: help \
        venv install \
        lint-local test-local type-check \
        local-setup local-up local-down local-restart local-logs \
        up down restart logs \
        migrate migrate-create migrate-down migrate-history migrate-local \
        build build-api shell-api shell-db shell-redis connect-db-info ps \
        lint test \
        worker-logs worker-restart beat-logs celery-status celery-inspect flower

# Chemins
VENV   := api/.venv
PYTHON := $(VENV)/bin/python
UV     := $(shell command -v uv 2>/dev/null)

help:
	@echo ""
	@echo "  n8n + FastAPI + PostgreSQL + Redis + Celery stack"
	@echo ""
	@echo "  ENVIRONNEMENT VIRTUEL (IDE / dev local sans Docker)"
	@echo "  make venv            — créer .venv dans api/ (uv ou pip)"
	@echo "  make install         — installer toutes les dépendances + dev"
	@echo "  make lint-local      — ruff check + format (depuis .venv)"
	@echo "  make test-local      — pytest avec SQLite, sans Docker"
	@echo "  make type-check      — mypy sur app/"
	@echo ""
	@echo "  STACK DOCKER (développement local)"
	@echo "  make local-setup     — copier .env.local → .env et démarrer"
	@echo "  make local-up        — démarrer (hot-reload activé)"
	@echo "  make local-down      — arrêter"
	@echo "  make local-logs      — logs de tous les services"
	@echo ""
	@echo "  CELERY"
	@echo "  make worker-logs     — logs du worker en temps réel"
	@echo "  make worker-restart  — redémarrer le worker (après modif tasks.py)"
	@echo "  make beat-logs       — logs du scheduler Beat"
	@echo "  make celery-status   — workers actifs et leurs queues"
	@echo "  make celery-inspect  — tâches actuellement en cours"
	@echo "  make flower          — UI Flower sur http://localhost:5555"
	@echo ""
	@echo "  PRODUCTION VPS"
	@echo "  make up              — démarrer sans override"
	@echo "  make down / logs"
	@echo ""
	@echo "  BASE DE DONNÉES"
	@echo "  make migrate                       — appliquer les migrations"
	@echo "  make migrate-create MSG='texte'    — générer une migration"
	@echo "  make migrate-down                  — rollback d'une migration"
	@echo ""
	@echo "  UTILITAIRES"
	@echo "  make build           — rebuild toutes les images Docker"
	@echo "  make shell-api       — bash dans le container API"
	@echo "  make shell-db        — psql dans appdb"
	@echo "  make shell-redis     — redis-cli dans le container Redis"
	@echo "  make ps              — état des containers"
	@echo ""

# ── Environnement virtuel ──────────────────────────────────

venv:
ifdef UV
	@echo "→ Création du venv avec uv ($(shell uv --version))"
	cd api && uv venv .venv --python 3.12
else
	@echo "→ uv non trouvé, utilisation de python3 -m venv"
	@echo "  (installe uv pour aller plus vite : curl -LsSf https://astral.sh/uv/install.sh | sh)"
	python3 -m venv api/.venv
endif
	@echo "✓ Venv créé dans api/.venv"
	@echo "  Active-le avec : source api/.venv/bin/activate"

install: venv
ifdef UV
	@echo "→ Installation des dépendances via uv"
	cd api && uv pip install -e ".[dev]"
else
	@echo "→ Installation des dépendances via pip"
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e "api/.[dev]"
endif
	@echo "✓ Dépendances installées dans api/.venv"

# ── Qualité de code locale (sans Docker) ──────────────────

lint-local: $(VENV)
	$(VENV)/bin/ruff check api/app/ --fix
	$(VENV)/bin/ruff format api/app/
	@echo "✓ Lint terminé"

type-check: $(VENV)
	cd api && $(abspath $(VENV))/bin/mypy app/ --ignore-missing-imports
	@echo "✓ Vérification de types terminée"

# ── Tests locaux (SQLite — Docker non requis) ─────────────

test-local: $(VENV)
	@echo "→ Tests avec SQLite en mémoire (sans Docker)"
	cd api && $(abspath $(VENV))/bin/pytest tests/ -v --asyncio-mode=auto
	@echo "✓ Tests terminés"

# Tests locaux contre Postgres + Redis du stack local
test-local-full: $(VENV)
	@echo "→ Tests complets (docker compose requis)"
	cd api && \
		TEST_DATABASE_URL="postgresql+asyncpg://admin:local_password@localhost:5434/appdb" \
		$(abspath $(VENV))/bin/pytest tests/ -v --asyncio-mode=auto

# ── Stack Docker (développement) ──────────────────────────

local-setup:
	@cp .env.local .env
	@echo "✓ .env créé depuis .env.local"
	@echo "→ Nettoyage des anciens containers..."
	docker compose down --remove-orphans 2>/dev/null || true
	$(MAKE) local-up

local-up:
	docker compose up -d --build --remove-orphans

local-down:
	docker compose down

local-restart:
	docker compose restart

local-logs:
	docker compose logs -f --tail=100

# ── Production ─────────────────────────────────────────────

up:
	docker compose -f docker-compose.yml up -d

down:
	docker compose -f docker-compose.yml down

restart:
	docker compose -f docker-compose.yml restart

logs:
	docker compose -f docker-compose.yml logs -f --tail=100

# ── Migrations Alembic ─────────────────────────────────────

migrate:
	docker compose exec api alembic upgrade head

migrate-create:
	@test -n "$(MSG)" || (echo "Usage: make migrate-create MSG='description'" && exit 1)
	docker compose exec api alembic revision --autogenerate -m "$(MSG)"

migrate-down:
	docker compose exec api alembic downgrade -1

migrate-history:
	docker compose exec api alembic history --verbose

migrate-local:
	cd api && $(abspath $(VENV))/bin/alembic upgrade head

# ── Celery ─────────────────────────────────────────────────

# Logs en temps réel
worker-logs:
	docker compose logs -f --tail=100 celery-worker

beat-logs:
	docker compose logs -f --tail=100 celery-beat

# Redémarrage du worker (obligatoire après modification de tasks.py en local)
worker-restart:
	docker compose restart celery-worker
	@echo "✓ Worker redémarré"

# État des workers connectés au broker
celery-status:
	docker compose exec celery-worker celery -A app.workers.celery_app status

# Tâches actuellement réservées / actives
celery-inspect:
	docker compose exec celery-worker celery -A app.workers.celery_app inspect active

# Purger toutes les tâches en attente dans la queue (ATTENTION : irréversible)
celery-purge:
	@echo "⚠ Purge de toutes les tâches en attente..."
	docker compose exec celery-worker celery -A app.workers.celery_app purge -f

# Flower — UI de monitoring Celery (http://localhost:5555)
flower:
	docker compose exec celery-worker \
		celery -A app.workers.celery_app flower --port=5555
	@echo "→ Flower disponible sur http://localhost:5555"

# ── Utilitaires Docker ─────────────────────────────────────

build:
	docker compose build --no-cache

build-api:
	docker compose build --no-cache api celery-worker celery-beat

shell-api:
	docker compose exec api bash

shell-db:
	docker compose exec postgres psql -U $${POSTGRES_USER:-admin} -d $${API_DB_NAME:-appdb}

shell-redis:
	docker compose exec redis redis-cli

connect-db-info:
	@echo "PostgreSQL → Host: localhost | Port: 5434 | User: $$(grep POSTGRES_USER .env | cut -d= -f2) | DB: $$(grep API_DB_NAME .env | cut -d= -f2)"
	@echo "Redis      → Host: localhost | Port: 6379"

ps:
	docker compose ps

# ── Qualité de code dans Docker ────────────────────────────

lint:
	docker compose exec api ruff check app/ --fix
	docker compose exec api ruff format app/

test:
	docker compose exec api pytest tests/ -v --asyncio-mode=auto

# ── Garde : vérifie que le venv existe ────────────────────

$(VENV):
	@echo "Venv absent — lance 'make install' d'abord"
	@exit 1
