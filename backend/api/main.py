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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deals import router as deals_router
from api.search import router as search_router
from core.config import get_settings
from core.database import init_db

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
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


@app.get(
    "/health",
    tags=["Info"],
    summary="Health check",
    description="Verifica o status da API e de suas dependências (Redis, DB).",
)
async def health_check():
    """
    Endpoint de health check para monitoramento e load balancers.

    Verifica:
        - Status geral da API
        - Conexão com Redis
        - Timestamp atual

    Returns:
        Dicionário com status de cada componente.
    """
    status_info = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "services": {},
    }

    # Verificar Redis
    global _redis_pool
    if _redis_pool is not None:
        try:
            await _redis_pool.ping()
            status_info["services"]["redis"] = "connected"
        except Exception:
            status_info["services"]["redis"] = "disconnected"
            status_info["status"] = "degraded"
    else:
        status_info["services"]["redis"] = "not_configured"
        status_info["status"] = "degraded"

    return status_info
