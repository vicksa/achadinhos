"""
Configuração de logging compartilhada entre a API e o bot.

Suporta dois formatos:
- "texto": legível, para desenvolvimento local (padrão).
- "json": uma linha JSON por log, com campos extras preservados — pensado
  para produção, onde um agregador de logs (ex: CloudWatch, Loki, ELK)
  consegue filtrar/consultar por campo em vez de fazer grep em texto.

Uso:
    logger.info("Falha ao coletar", extra={"source": "pelando", "event": "fetch_failed"})

Em formato JSON isso vira:
    {"timestamp": "...", "level": "ERROR", "service": "scrapers.pelando_scraper",
     "message": "Falha ao coletar", "source": "pelando", "event": "fetch_failed"}
"""

import json
import logging
import sys
from datetime import datetime, timezone

# Campos padrão de um LogRecord — usados para descobrir quais campos são
# "extras" adicionados via `extra={...}` nas chamadas de log.
_CAMPOS_PADRAO_LOG_RECORD = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)


class JsonFormatter(logging.Formatter):
    """Formata cada registro de log como um objeto JSON de uma linha só."""

    def format(self, record: logging.LogRecord) -> str:
        dados = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "service": record.name,
            "message": record.getMessage(),
        }

        for chave, valor in record.__dict__.items():
            if chave not in _CAMPOS_PADRAO_LOG_RECORD and chave not in dados:
                dados[chave] = valor

        if record.exc_info:
            dados["exception"] = self.formatException(record.exc_info)

        return json.dumps(dados, ensure_ascii=False, default=str)


_FORMATO_TEXTO = "%(asctime)s │ %(levelname)-8s │ %(name)-25s │ %(message)s"
_DATA_FORMATO_TEXTO = "%Y-%m-%d %H:%M:%S"


def configurar_logging(nivel: str = "INFO", formato: str = "texto") -> None:
    """
    Configura o logging raiz da aplicação (API ou bot).

    Args:
        nivel: Nível mínimo de log (DEBUG, INFO, WARNING, ERROR...).
        formato: "json" para logs estruturados, "texto" (padrão) para o
            formato legível usado em desenvolvimento local.
    """
    handler = logging.StreamHandler(sys.stdout)

    if formato == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_FORMATO_TEXTO, datefmt=_DATA_FORMATO_TEXTO))

    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        handlers=[handler],
        force=True,  # substitui qualquer configuração anterior (ex: básica do FastAPI)
    )

    # Reduzir verbosidade de bibliotecas externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
