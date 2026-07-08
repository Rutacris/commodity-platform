import time

import requests
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.config import get_settings
from db.session import get_db

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health", summary="Liveness check")
def health():
    return {"status": "ok", "service": settings.APP_NAME}


@router.get("/health/ready", summary="Readiness check (DB + Ollama)")
def readiness(db: Session = Depends(get_db)):
    result = {"status": "ok", "checks": {}}

    # Database
    try:
        db.execute(text("SELECT 1"))
        result["checks"]["database"] = "ok"
    except Exception as e:
        result["checks"]["database"] = f"error: {e}"
        result["status"] = "degraded"

    # Ollama
    try:
        t0 = time.time()
        resp = requests.get(f"{settings.OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        result["checks"]["ollama"] = {
            "status": "ok",
            "latency_ms": round((time.time() - t0) * 1000),
            "models": models,
        }
    except Exception as e:
        result["checks"]["ollama"] = f"unavailable: {e}"
        # Ollama being down is degraded, not fatal
        if result["status"] == "ok":
            result["status"] = "degraded"

    return result
