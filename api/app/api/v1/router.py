from fastapi import APIRouter, Depends

from app.api.v1.endpoints import health, tasks
from app.core.security import verify_api_key

router = APIRouter()

# Health/ping : public — pas de clé requise (monitoring, load balancer)
router.include_router(health.router, tags=["monitoring"])

# Tasks : protégé par X-API-Key sur toutes les routes
router.include_router(
    tasks.router,
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(verify_api_key)],
)
