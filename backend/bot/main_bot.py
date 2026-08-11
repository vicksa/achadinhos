"""
Ponto de entrada principal do Bot de Achadinhos.

Inicializa todos os serviços necessários e inicia o loop
de coleta e publicação automática de ofertas.

Uso:
    cd backend/
    python -m bot.main_bot

Serviços inicializados:
1. Logging estruturado
2. Conexão Redis (deduplicação)
3. Banco de dados PostgreSQL (criação de tabelas)
4. Scheduler APScheduler (pipeline periódico)
5. Execução inicial do pipeline

O processo roda indefinidamente até receber SIGINT (Ctrl+C)
ou SIGTERM.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from core.config import get_settings

logger = logging.getLogger("achadinhos")


def _configurar_logging() -> None:
    """
    Configura o sistema de logging com formato estruturado.

    Usa o nível de log definido nas configurações (LOG_LEVEL).
    """
    settings = get_settings()

    formato = (
        "%(asctime)s │ %(levelname)-8s │ %(name)-25s │ %(message)s"
    )
    data_formato = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=formato,
        datefmt=data_formato,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduzir verbosidade de libs externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    logger.info("Logging configurado (nível: %s).", settings.log_level)


async def _inicializar_redis() -> None:
    """Inicializa a conexão com o Redis para deduplicação."""
    from bot.dedup import init_redis

    try:
        await init_redis()
        logger.info("✅ Redis inicializado com sucesso.")
    except Exception as exc:
        logger.error(
            "⚠️  Falha ao conectar no Redis: %s. "
            "O bot continuará sem deduplicação.",
            exc,
        )


async def _inicializar_banco() -> None:
    """
    Inicializa o banco de dados, criando tabelas se necessário.

    Importa os modelos para garantir que o metadata do SQLAlchemy
    conhece todas as tabelas antes de criar.
    """
    from core.database import init_db

    try:
        # Importar modelos para registrar no metadata
        import core.models  # noqa: F401

        await init_db()
        logger.info("✅ Banco de dados inicializado (tabelas criadas/verificadas).")
    except Exception as exc:
        logger.error(
            "❌ Falha ao inicializar o banco de dados: %s. "
            "O bot não conseguirá salvar ofertas.",
            exc,
            exc_info=True,
        )
        raise


async def _executar_pipeline_inicial() -> None:
    """
    Executa o pipeline uma vez ao iniciar, para não esperar
    o primeiro intervalo do scheduler.
    """
    from bot.scheduler import executar_pipeline_agora

    logger.info("🚀 Executando pipeline inicial...")
    try:
        await executar_pipeline_agora()
    except Exception as exc:
        logger.error(
            "Erro no pipeline inicial (não-fatal): %s",
            exc,
            exc_info=True,
        )


async def _main() -> None:
    """
    Função principal assíncrona.

    Orquestra a inicialização de todos os serviços e mantém
    o bot rodando até receber sinal de parada.
    """
    settings = get_settings()

    logger.info(
        "╔═══════════════════════════════════════════════════════╗\n"
        "║          🤖 Bot de Achadinhos — Iniciando            ║\n"
        "╠═══════════════════════════════════════════════════════╣\n"
        "║  Ambiente: %-41s ║\n"
        "║  Intervalo: %d min                                   ║\n"
        "║  Desconto mín.: %.0f%%                                ║\n"
        "║  Canal TG: %-41s ║\n"
        "╚═══════════════════════════════════════════════════════╝",
        settings.environment,
        settings.deal_check_interval_minutes,
        settings.deal_min_discount_pct,
        settings.telegram_channel_id,
    )

    # ── Verificar token do Telegram ──────────────────────────────────
    if settings.telegram_bot_token == "SEU_TOKEN_AQUI":
        logger.warning(
            "⚠️  Token do Telegram é placeholder! "
            "Configure TELEGRAM_BOT_TOKEN no .env para publicar ofertas."
        )

    # ── Inicializar serviços ─────────────────────────────────────────
    await _inicializar_redis()
    await _inicializar_banco()

    # ── Configurar scheduler ─────────────────────────────────────────
    from bot.scheduler import criar_scheduler, parar_scheduler

    scheduler = criar_scheduler()
    scheduler.start()
    logger.info(
        "✅ Scheduler iniciado — próxima execução a cada %d minutos.",
        settings.deal_check_interval_minutes,
    )

    # ── Executar pipeline inicial ────────────────────────────────────
    await _executar_pipeline_inicial()

    # ── Manter rodando até sinal de parada ───────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        """Handler para sinais de parada (SIGINT, SIGTERM)."""
        sig_name = signal.Signals(signum).name
        logger.info("Sinal %s recebido. Encerrando bot...", sig_name)
        stop_event.set()

    # Registrar handlers de sinal
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "🟢 Bot rodando! Pressione Ctrl+C para parar."
    )

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Encerrando serviços...")
        parar_scheduler()

        # Fechar Redis
        from bot.dedup import fechar_redis
        await fechar_redis()

        logger.info(
            "╔═══════════════════════════════════════════════════════╗\n"
            "║       🛑 Bot de Achadinhos — Encerrado               ║\n"
            "║       Horário: %-37s ║\n"
            "╚═══════════════════════════════════════════════════════╝",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )


def main() -> None:
    """
    Ponto de entrada síncrono.

    Configura logging e executa o loop async principal.
    """
    _configurar_logging()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Bot interrompido pelo usuário.")
    except Exception as exc:
        logger.critical(
            "Erro fatal no bot: %s",
            exc,
            exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
