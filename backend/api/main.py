"""
Aplicação principal FastAPI — Price Aggregator API.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.deals import router as deals_router
from api.search import router as search_router
from api.tracking import router as tracking_router
from core.config import get_settings
from core.database import engine, init_db
from core.logging_config import configurar_logging

_settings_iniciais = get_settings()
configurar_logging(nivel=_settings_iniciais.log_level, formato=_settings_iniciais.log_format)
logger = logging.getLogger(__name__)

_redis_pool: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis_pool
    settings = get_settings()
    logger.info("🚀 Iniciando Price Aggregator API...")

    try:
        _redis_pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
        await _redis_pool.ping()
        logger.info("✅ Redis conectado: %s", settings.redis_url)
    except Exception as exc:
        logger.warning("⚠️ Redis indisponível (%s) — API funcionará sem cache.", exc)
        _redis_pool = None

    try:
        if settings.environment == "development":
            await init_db()
            logger.info("✅ Banco de dados inicializado (tabelas criadas/verificadas)")
        else:
            logger.info("✅ Banco de dados configurado (modo produção)")
    except Exception as exc:
        logger.warning("⚠️ Banco de dados indisponível (%s).", exc)

    logger.info("✅ Price Aggregator API pronta!")
    yield

    logger.info("🔌 Encerrando Price Aggregator API...")
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("Redis desconectado.")
    logger.info("Bye! 👋")


app = FastAPI(
    title="Price Aggregator API — Achadinhos",
    description=(
        "API de comparação de preços e achadinhos para e-commerce brasileiro, "
        "com rastreamento de tráfego afiliado."
    ),
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router)
app.include_router(deals_router)
app.include_router(tracking_router)


@app.get("/", tags=["Info"], summary="Informações da API")
async def raiz():
    return {
        "api": "Price Aggregator — Achadinhos",
        "versao": "1.1.0",
        "descricao": "API de comparação de preços e monetização de achadinhos.",
        "documentacao": "/docs",
        "endpoints": {
            "achadinhos": "/api/deals?q=termo",
            "busca": "/api/search?q=termo",
            "sugestoes": "/api/search/suggestions?q=prefixo",
            "tracking": "/go/{deal_id}?src=instagram",
            "health": "/health",
        },
    }


async def _checar_redis() -> str:
    if _redis_pool is None:
        return "not_configured"
    try:
        await _redis_pool.ping()
        return "connected"
    except Exception:
        return "disconnected"


async def _checar_banco() -> str:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "disconnected"


async def _checar_bot_heartbeat() -> str:
    if _redis_pool is None:
        return "unknown"
    try:
        from bot.dedup import HEARTBEAT_KEY
        valor = await _redis_pool.get(HEARTBEAT_KEY)
        return "ok" if valor is not None else "unknown"
    except Exception:
        return "unknown"


@app.get("/health", tags=["Info"], summary="Health check")
async def health_check():
    redis_status = await _checar_redis()
    db_status = await _checar_banco()
    bot_status = await _checar_bot_heartbeat()
    degradado = redis_status != "connected" or db_status != "connected"
    return {
        "status": "degraded" if degradado else "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.1.0",
        "services": {
            "redis": redis_status,
            "database": db_status,
            "bot": bot_status,
        },
    }


@app.get("/ready", tags=["Info"], summary="Readiness check")
async def readiness_check(response: Response):
    db_status = await _checar_banco()
    pronto = db_status == "connected"
    if not pronto:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": pronto, "database": db_status}
