"""
Publisher de ofertas para o Telegram.

Envia cards de ofertas como fotos com legenda HTML formatada
e botão inline "🛒 Comprar agora" linkando para a URL da oferta.
Trata rate limits, erros de rede e tokens inválidos de forma resiliente.
"""

import asyncio
import io
import logging
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TimedOut,
    TelegramError,
)

from core.config import get_settings

logger = logging.getLogger(__name__)

# Token placeholder que indica configuração pendente
_TOKEN_PLACEHOLDER = "SEU_TOKEN_AQUI"

# Número máximo de tentativas em caso de erro transiente
_MAX_TENTATIVAS = 3


def _formatar_preco_br(valor: float | None) -> str:
    """
    Formata valor numérico como preço brasileiro.

    Args:
        valor: Valor a formatar.

    Returns:
        String formatada (ex: 'R$ 1.299,90') ou string vazia.
    """
    if valor is None:
        return ""
    inteiro = int(valor)
    decimal = int(round((valor - inteiro) * 100))
    inteiro_str = f"{inteiro:,}".replace(",", ".")
    return f"R$ {inteiro_str},{decimal:02d}"


def _montar_caption(deal: dict[str, Any]) -> str:
    """
    Monta a legenda HTML para a foto do Telegram.

    Formato:
        🔥 <b>Título do Produto</b>

        💰 <s>De: R$ 999,90</s>
        ✅ <b>Por: R$ 599,90</b>
        📉 Desconto: -33%

        🏪 Loja: Amazon

    Args:
        deal: Dicionário com dados da oferta.

    Returns:
        String HTML formatada para caption.
    """
    partes: list[str] = []

    # Título
    titulo = deal.get("title", "Oferta Especial")
    partes.append(f"🔥 <b>{_escapar_html(titulo)}</b>")
    partes.append("")  # Linha em branco

    # Preço original (riscado)
    preco_original = deal.get("price_original")
    if preco_original:
        preco_orig_str = _formatar_preco_br(preco_original)
        partes.append(f"💰 <s>De: {preco_orig_str}</s>")

    # Preço atual
    preco = deal.get("price")
    if preco:
        preco_str = _formatar_preco_br(preco)
        partes.append(f"✅ <b>Por: {preco_str}</b>")

    # Desconto
    desconto = deal.get("discount_pct")
    if desconto and desconto > 0:
        partes.append(f"📉 Desconto: <b>-{int(desconto)}%</b>")

    partes.append("")  # Linha em branco

    # Loja
    loja = deal.get("store")
    if loja:
        partes.append(f"🏪 Loja: {_escapar_html(loja)}")

    # Descrição breve (se houver, limitada)
    descricao = deal.get("description")
    if descricao:
        desc_curta = descricao[:200]
        if len(descricao) > 200:
            desc_curta += "..."
        partes.append("")
        partes.append(f"📝 {_escapar_html(desc_curta)}")

    return "\n".join(partes)


def _escapar_html(texto: str) -> str:
    """
    Escapa caracteres especiais para HTML do Telegram.

    Args:
        texto: Texto a escapar.

    Returns:
        Texto com caracteres especiais escapados.
    """
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _montar_teclado(deal: dict[str, Any]) -> InlineKeyboardMarkup:
    """
    Monta o teclado inline com o botão de compra.

    Usa affiliate_url se disponível, senão a URL original.

    Args:
        deal: Dicionário com dados da oferta.

    Returns:
        InlineKeyboardMarkup com o botão de compra.
    """
    url = deal.get("affiliate_url") or deal.get("url", "")
    botao = InlineKeyboardButton(
        text="🛒 Comprar agora",
        url=url,
    )
    return InlineKeyboardMarkup([[botao]])


async def publicar_no_telegram(
    deal: dict[str, Any],
    card_image: bytes,
) -> int | None:
    """
    Publica uma oferta no canal do Telegram.

    Envia a imagem do card como foto, com legenda HTML formatada
    e botão inline para compra. Lida com rate limits (RetryAfter)
    esperando o tempo necessário antes de tentar novamente.

    Args:
        deal: Dicionário com dados da oferta.
        card_image: Bytes da imagem PNG do card.

    Returns:
        ID da mensagem enviada, ou None em caso de falha.

    Raises:
        Não levanta exceções — todos os erros são tratados
        internamente com logging adequado.
    """
    settings = get_settings()

    # Verificar se o token está configurado
    if settings.telegram_bot_token == _TOKEN_PLACEHOLDER:
        logger.warning(
            "Token do Telegram não configurado (placeholder detectado). "
            "Pulando publicação de: %s",
            deal.get("title", "???")[:60],
        )
        return None

    bot = Bot(token=settings.telegram_bot_token)
    caption = _montar_caption(deal)
    teclado = _montar_teclado(deal)
    channel_id = settings.telegram_channel_id

    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        try:
            # Criar InputFile a partir dos bytes
            photo_file = io.BytesIO(card_image)
            photo_file.name = "deal_card.png"

            mensagem = await bot.send_photo(
                chat_id=channel_id,
                photo=photo_file,
                caption=caption,
                parse_mode="HTML",
                reply_markup=teclado,
            )

            logger.info(
                "Oferta publicada no Telegram com sucesso! "
                "message_id=%d, canal=%s, título=%s",
                mensagem.message_id,
                channel_id,
                deal.get("title", "???")[:50],
            )
            return mensagem.message_id

        except RetryAfter as exc:
            wait_time = exc.retry_after + 1
            logger.warning(
                "Rate limit do Telegram! Aguardando %ds antes de tentar "
                "novamente (tentativa %d/%d).",
                wait_time,
                tentativa,
                _MAX_TENTATIVAS,
            )
            await asyncio.sleep(wait_time)

        except TimedOut:
            logger.warning(
                "Timeout ao enviar para o Telegram (tentativa %d/%d). "
                "Aguardando 5s...",
                tentativa,
                _MAX_TENTATIVAS,
            )
            await asyncio.sleep(5)

        except BadRequest as exc:
            logger.error(
                "Erro de requisição inválida ao Telegram: %s — "
                "Título: %s",
                exc,
                deal.get("title", "???")[:60],
            )
            # Erro de requisição inválida não é retryable
            return None

        except Forbidden as exc:
            logger.error(
                "Bot sem permissão para postar no canal %s: %s",
                channel_id,
                exc,
            )
            # Erro de permissão não é retryable
            return None

        except NetworkError as exc:
            logger.warning(
                "Erro de rede ao enviar para o Telegram: %s "
                "(tentativa %d/%d). Aguardando 3s...",
                exc,
                tentativa,
                _MAX_TENTATIVAS,
            )
            await asyncio.sleep(3)

        except TelegramError as exc:
            logger.error(
                "Erro genérico do Telegram (tentativa %d/%d): %s",
                tentativa,
                _MAX_TENTATIVAS,
                exc,
            )
            if tentativa < _MAX_TENTATIVAS:
                await asyncio.sleep(2)

        except Exception as exc:
            logger.error(
                "Erro inesperado ao publicar no Telegram: %s",
                exc,
                exc_info=True,
            )
            return None

    logger.error(
        "Falha ao publicar no Telegram após %d tentativas: %s",
        _MAX_TENTATIVAS,
        deal.get("title", "???")[:60],
    )
    return None
