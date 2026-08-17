"""
Aplicação principal FastAPI — Price Aggregator API.

Configura o app com lifespan (Redis + DB), CORS para o frontend Next.js,
e registra os routers de busca, health check e informações da API.

Execução:
    cd backend && source venv/bin/activate
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
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
from core.config import get_settings
from core.database import engine, init_db
from core.logging_config import configurar_logging

# ---- Logging ----
_settings_iniciais = get_settings()
configurar_logging(nivel=_settings_iniciais.log_level, formato=_settings_iniciais.log_format)
logger = logging.getLogger(__name__)

# ---- Pool Redis global (acessado pelo router de busca) ----
_redis_pool: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação.

    Startup:
        - Inicializa pool de conexão Redis
        - Inicializa banco de dados (cria tabelas em dev)

    Shutdown:
        - Fecha conexão Redis
        - Limpa recursos
    """
    global _redis_pool
    settings = get_settings()

    # ---- STARTUP ----
    logger.info("🚀 Iniciando Price Aggregator API...")

    # Redis
    try:
        _redis_pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
        # Testar conexão
        await _redis_pool.ping()
        logger.info("✅ Redis conectado: %s", settings.redis_url)
    except Exception as exc:
        logger.warning(
            "⚠️  Redis indisponível (%s) — API funcionará sem cache.",
            exc,
        )
        _redis_pool = None

    # Banco de dados
    try:
        if settings.environment == "development":
            await init_db()
            logger.info("✅ Banco de dados inicializado (tabelas criadas/verificadas)")
        else:
            logger.info("✅ Banco de dados configurado (modo produção)")
    except Exception as exc:
        logger.warning(
            "⚠️  Banco de dados indisponível (%s) — endpoints de busca "
            "funcionarão normalmente (sem persistência).",
            exc,
        )

    logger.info("✅ Price Aggregator API pronta!")

    yield

    # ---- SHUTDOWN ----
    logger.info("🔌 Encerrando Price Aggregator API...")

    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("Redis desconectado.")

    logger.info("Bye! 👋")


# ---- App FastAPI ----
app = FastAPI(
    title="Price Aggregator API — Achadinhos",
    description=(
        "API de comparação de preços para e-commerce brasileiro. "
        "Agrega ofertas do Mercado Livre, Amazon e outros marketplaces "
        "em uma interface unificada com cache inteligente."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ---- CORS ----
ALLOWED_ORIGINS = [
    "http://localhost:3000",       # Next.js dev
    "http://127.0.0.1:3000",      # Next.js dev (alias)
    "http://localhost:8000",       # Swagger UI
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Routers ----
app.include_router(search_router)
app.include_router(deals_router)


# ---- Endpoints raiz ----
@app.get(
    "/",
    tags=["Info"],
    summary="Informações da API",
    description="Retorna metadados sobre a API, versão e endpoints disponíveis.",
)
async def raiz():
    """Endpoint raiz com informações gerais da API."""
    return {
        "api": "Price Aggregator — Achadinhos",
        "versao": "1.0.0",
        "descricao": (
            "API de comparação de preços para e-commerce brasileiro."
        ),
        "documentacao": "/docs",
        "endpoints": {
            "achadinhos": "/api/deals?q=termo",
            "busca": "/api/search?q=termo",
            "sugestoes": "/api/search/suggestions?q=prefixo",
            "health": "/health",
        },
    }


async def _checar_redis() -> str:
    """Retorna 'connected', 'disconnected' ou 'not_configured'."""
    if _redis_pool is None:
        return "not_configured"
    try:
        await _redis_pool.ping()
        return "connected"
    except Exception:
        return "disconnected"


async def _checar_banco() -> str:
    """Retorna 'connected' ou 'disconnected'."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "disconnected"


async def _checar_bot_heartbeat() -> str:
    """
    Retorna 'ok' ou 'unknown' (nunca reportou / parou de reportar / Redis
    indisponível).

    O bot grava a chave `HEARTBEAT_KEY` no Redis a cada ciclo do pipeline
    (ver bot/dedup.py e bot/scheduler.py), com TTL de ~2x o intervalo do
    pipeline — isso permite monitorar de fora se ele ainda está vivo, sem
    expor uma porta HTTP no processo do bot. O TTL expira sozinho se o
    bot parar, então "unknown" cobre tanto "nunca rodou" quanto "travou".
    """
    if _redis_pool is None:
        return "unknown"
    try:
        from bot.dedup import HEARTBEAT_KEY

        valor = await _redis_pool.get(HEARTBEAT_KEY)
        return "ok" if valor is not None else "unknown"
    except Exception:
        return "unknown"


@app.get(
    "/health",
    tags=["Info"],
    summary="Health check",
    description="Verifica o status da API e de suas dependências (Redis, DB, bot).",
)
async def health_check():
    """
    Endpoint de health check (liveness) para monitoramento e load balancers.

    Diferente de `/ready`, sempre responde 200 — o objetivo aqui é
    reportar o status de cada componente, não decidir se a API deve
    receber tráfego (isso é papel do `/ready`).
    """
    redis_status = await _checar_redis()
    db_status = await _checar_banco()
    bot_status = await _checar_bot_heartbeat()

    degradado = redis_status != "connected" or db_status != "connected"

    return {
        "status": "degraded" if degradado else "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "services": {
            "redis": redis_status,
            "database": db_status,
            "bot": bot_status,
        },
    }


@app.get(
    "/ready",
    tags=["Info"],
    summary="Readiness check",
    description=(
        "Indica se a API está pronta para receber tráfego — responde 503 "
        "se uma dependência essencial (banco de dados) estiver indisponível."
    ),
)
async def readiness_check(response: Response):
    """
    Endpoint de readiness, no sentido usado por orquestradores (ex:
    Kubernetes): diferente de `/health`, aqui uma dependência essencial
    fora do ar deve tirar a instância de circulação (503), não só
    reportar como "degraded".

    O banco é considerado essencial (os endpoints de achadinhos dependem
    dele). O Redis não é — a API funciona sem cache, só mais lenta.
    """
    db_status = await _checar_banco()
    pronto = db_status == "connected"

    if not pronto:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "ready": pronto,
        "database": db_status,
    }
