"""Bootstrap idempotente do schema para ambientes de deploy.

O projeto ainda não usa Alembic. Este módulo cria tabelas ausentes e aplica
as pequenas alterações compatíveis já suportadas pelo projeto antes da API
subir. Pode ser executado várias vezes sem recriar dados existentes.
"""

import asyncio
import logging

import core.models  # noqa: F401 - registra os modelos no metadata
from core.database import init_db
from core.logging_config import configurar_logging
from core.config import get_settings

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    configurar_logging(nivel=settings.log_level, formato=settings.log_format)
    logger.info("Inicializando/verificando schema do banco...")
    await init_db()
    logger.info("Schema do banco pronto.")


if __name__ == "__main__":
    asyncio.run(main())
