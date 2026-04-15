"""
Celery application — broker Redis, backend Redis.

Démarrage du worker :
  celery -A app.workers.celery_app worker --loglevel=info --queues=tasks,default

Démarrage du scheduler :
  celery -A app.workers.celery_app beat --loglevel=info

Monitoring (Flower) :
  celery -A app.workers.celery_app flower
"""

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging
from celery.utils.log import get_task_logger
from prometheus_client import Counter, Histogram

from app.core.config import get_settings

settings = get_settings()

# ── Celery app ─────────────────────────────────────────────
celery_app = Celery(
    "n8n-stack",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

# ── Configuration ──────────────────────────────────────────
celery_app.conf.update(
    # Sérialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone=settings.timezone,
    enable_utc=True,
    # Fiabilité
    task_track_started=True,
    task_acks_late=True,  # ack APRÈS exécution (pas avant) → pas de perte en cas de crash
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # distribution équitable entre workers
    # Résultats
    result_expires=3600,  # résultats conservés 1h dans Redis
    # Routes de queues
    task_routes={
        "app.workers.tasks.run_task": {"queue": "tasks"},
    },
    # Retry par défaut
    task_default_retry_delay=settings.celery_task_retry_backoff,
    task_max_retries=settings.celery_task_max_retries,
)


# ── Logging — délégué à structlog ──────────────────────────
@celery_setup_logging.connect
def configure_celery_logging(**kwargs):
    from app.core.logging import setup_logging

    setup_logging()


logger = get_task_logger(__name__)

# ── Sentry ─────────────────────────────────────────────────
if settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.api_env,
        integrations=[CeleryIntegration()],
        send_default_pii=False,
    )

# ── Métriques Prometheus (partagées avec tasks.py) ─────────
celery_tasks_total = Counter(
    "celery_tasks_total",
    "Nombre total de tâches Celery par type et statut",
    ["task_type", "status"],
)
celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds",
    "Durée d'exécution des tâches Celery en secondes",
    ["task_type"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)
