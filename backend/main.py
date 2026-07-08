from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from api.routers import data_ingestion, health, insights, prices
from fastapi import APIRouter

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(prices.router)
api_router.include_router(insights.router)
api_router.include_router(data_ingestion.router)
from core.config import get_settings
from db.session import Base, engine

settings = get_settings()
templates = Jinja2Templates(directory="templates")


# ── Startup / shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (idempotent — safe with existing schema)
    Base.metadata.create_all(bind=engine)
    yield
    # Nothing to clean up (connection pool handles itself)


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Rwanda commodity price tracking API. "
            "Aggregates prices for Maize, Beans, Rice, Cooking Oil, and Sugar "
            "across major Rwandan markets via multiple data sources."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(api_router)

    # ── Root redirect to docs ─────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse({
            "service":  settings.APP_NAME,
            "version":  settings.APP_VERSION,
            "docs":     "/docs",
            "health":   "/health",
            "endpoints": {
                "latest_prices":      "/prices/latest",
                "all_prices":         "/prices",
                "commodity_summary":  "/prices/summary/commodities",
                "market_summary":     "/prices/summary/markets",
                "price_trend":        "/prices/trend/{commodity}",
                "ai_insight":         "/insights",
                "ingest_ui":          "/ingest/ui",
            },
        })

    @app.get("/ingest/ui", include_in_schema=False)
    async def ingest_ui(request: Request):
        return templates.TemplateResponse(request, "ingest.html")

    return app


app = create_app()