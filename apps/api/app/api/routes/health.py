"""Health / readiness endpoints."""
from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.PROJECT_NAME, "environment": settings.ENVIRONMENT}


@router.get("/health/db")
def health_db(db: DbSession) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
