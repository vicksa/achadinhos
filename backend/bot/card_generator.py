"""
Gerador de cards visuais para ofertas (deals).

Cria imagens PNG 1080×1080 com design moderno e atraente:
- Fundo gradiente escuro (slate-900 → slate-800)
- Título do produto em branco (bold)
- Preço original riscado (cinza)
- Preço atual em verde (destaque)
- Badge de desconto em vermelho
- Nome da loja
- Rodapé com marca d'água

Usa fontes DejaVu Sans (disponíveis no Linux) com fallback.
"""

import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── Dimensões do card ────────────────────────────────────────────────
CARD_WIDTH = 1080
CARD_HEIGHT = 1080

# ── Paleta de cores ──────────────────────────────────────────────────
COR_FUNDO_TOPO = (15, 23, 42)        # slate-900
COR_FUNDO_BASE = (30, 41, 59)        # slate-800
COR_TITULO = (255, 255, 255)         # branco
COR_PRECO_ORIGINAL = (148, 163, 184) # slate-400 (cinza)
COR_PRECO_ATUAL = (34, 197, 94)      # green-500
COR_BADGE_FUNDO = (220, 38, 38)      # red-600
COR_BADGE_TEXTO = (255, 255, 255)    # branco
COR_LOJA = (148, 163, 184)           # slate-400
COR_RODAPE = (100, 116, 139)         # slate-500
COR_SEPARADOR = (51, 65, 85)         # slate-700
COR_SUBTITULO = (203, 213, 225)      # slate-300

# ── Margens e espaçamentos ───────────────────────────────────────────
MARGEM_X = 80
MARGEM_Y = 80
ESPACAMENTO = 24

# ── Caminhos de fontes (DejaVu Sans — padrão no Linux) ──────────────
_CAMINHOS_FONTES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]

_CAMINHOS_FONTES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _carregar_fonte(caminhos: list[str], tamanho: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Tenta carregar uma fonte TrueType a partir de uma lista de caminhos.

    Se nenhum caminho funcionar, retorna a fonte padrão do Pillow.

    Args:
        caminhos: Lista de caminhos possíveis da fonte.
        tamanho: Tamanho desejado da fonte.

    Returns:
        Objeto de fonte carregado.
    """
    for caminho in caminhos:
        if Path(caminho).exists():
            try:
                return ImageFont.truetype(caminho, tamanho)
            except (OSError, IOError):
                continue

    logger.warning(
        "Nenhuma fonte TrueType encontrada em %s. Usando fonte padrão.",
        caminhos,
    )
    return ImageFont.load_default()


def _obter_fontes() -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """
    Carrega todas as fontes necessárias para o card.

    Returns:
        Dicionário com as fontes nomeadas.
    """
    return {
        "titulo": _carregar_fonte(_CAMINHOS_FONTES_BOLD, 44),
        "preco_original": _carregar_fonte(_CAMINHOS_FONTES_REGULAR, 32),
        "preco_atual": _carregar_fonte(_CAMINHOS_FONTES_BOLD, 72),
        "badge": _carregar_fonte(_CAMINHOS_FONTES_BOLD, 36),
        "loja": _carregar_fonte(_CAMINHOS_FONTES_REGULAR, 30),
        "rodape": _carregar_fonte(_CAMINHOS_FONTES_REGULAR, 22),
        "label": _carregar_fonte(_CAMINHOS_FONTES_REGULAR, 26),
    }


def _desenhar_gradiente(img: Image.Image) -> None:
    """
    Desenha um gradiente vertical de slate-900 (topo) a slate-800 (base).

    Args:
        img: Imagem PIL para desenhar o gradiente.
    """
    draw = ImageDraw.Draw(img)
    for y in range(CARD_HEIGHT):
        ratio = y / CARD_HEIGHT
        r = int(COR_FUNDO_TOPO[0] + (COR_FUNDO_BASE[0] - COR_FUNDO_TOPO[0]) * ratio)
        g = int(COR_FUNDO_TOPO[1] + (COR_FUNDO_BASE[1] - COR_FUNDO_TOPO[1]) * ratio)
        b = int(COR_FUNDO_TOPO[2] + (COR_FUNDO_BASE[2] - COR_FUNDO_TOPO[2]) * ratio)
        draw.line([(0, y), (CARD_WIDTH, y)], fill=(r, g, b))


def _quebrar_texto(
    texto: str,
    fonte: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    largura_max: int,
    draw: ImageDraw.Draw,
) -> list[str]:
    """
    Quebra texto em múltiplas linhas para caber na largura máxima.

    Args:
        texto: Texto a ser quebrado.
        fonte: Fonte para calcular largura.
        largura_max: Largura máxima em pixels.
        draw: Objeto ImageDraw para medição.

    Returns:
        Lista de linhas de texto.
    """
    palavras = texto.split()
    linhas: list[str] = []
    linha_atual = ""

    for palavra in palavras:
        teste = f"{linha_atual} {palavra}".strip()
        bbox = draw.textbbox((0, 0), teste, font=fonte)
        largura = bbox[2] - bbox[0]

        if largura <= largura_max:
            linha_atual = teste
        else:
            if linha_atual:
                linhas.append(linha_atual)
            linha_atual = palavra

    if linha_atual:
        linhas.append(linha_atual)

    return linhas or [texto]


def _formatar_preco(valor: float | None) -> str:
    """
    Formata um valor numérico como preço brasileiro.

    Args:
        valor: Valor a formatar.

    Returns:
        String formatada (ex: 'R$ 1.299,90').
    """
    if valor is None:
        return ""
    # Formatar com 2 casas decimais
    inteiro = int(valor)
    decimal = int(round((valor - inteiro) * 100))
    # Adicionar separadores de milhar
    inteiro_str = f"{inteiro:,}".replace(",", ".")
    return f"R$ {inteiro_str},{decimal:02d}"


def _desenhar_riscado(
    draw: ImageDraw.Draw,
    posicao: tuple[int, int],
    texto: str,
    fonte: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    cor: tuple[int, int, int],
) -> int:
    """
    Desenha texto com efeito de riscado (strikethrough).

    Args:
        draw: Objeto ImageDraw.
        posicao: Coordenada (x, y).
        texto: Texto a desenhar.
        fonte: Fonte a usar.
        cor: Cor do texto e da linha.

    Returns:
        Largura total do texto desenhado.
    """
    x, y = posicao
    draw.text((x, y), texto, font=fonte, fill=cor)
    bbox = draw.textbbox((x, y), texto, font=fonte)
    largura = bbox[2] - bbox[0]
    altura = bbox[3] - bbox[1]
    # Linha riscada no meio do texto
    y_risco = y + altura // 2 + 2
    draw.line([(x, y_risco), (x + largura, y_risco)], fill=cor, width=3)
    return largura


def generate_deal_card(deal: dict[str, Any]) -> bytes:
    """
    Gera um card visual PNG 1080×1080 para uma oferta.

    Cria uma imagem com design moderno contendo:
    - Fundo gradiente escuro
    - Título do produto (com quebra de linha)
    - Preço original riscado e preço atual em destaque
    - Badge de desconto percentual
    - Nome da loja
    - Rodapé com marca d'água

    Args:
        deal: Dicionário com dados da oferta. Campos usados:
            - title (str): Título do produto.
            - price (float|None): Preço atual.
            - price_original (float|None): Preço original.
            - discount_pct (float|None): Percentual de desconto.
            - store (str|None): Nome da loja.

    Returns:
        Bytes do PNG gerado.
    """
    fontes = _obter_fontes()

    # Criar imagem com gradiente
    img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT))
    _desenhar_gradiente(img)
    draw = ImageDraw.Draw(img)

    # Área de conteúdo (com margens)
    area_largura = CARD_WIDTH - 2 * MARGEM_X
    cursor_y = MARGEM_Y

    # ── Cabeçalho: emoji + "OFERTA ENCONTRADA" ──────────────────────
    header = "🔥 OFERTA ENCONTRADA"
    draw.text(
        (MARGEM_X, cursor_y),
        header,
        font=fontes["label"],
        fill=COR_BADGE_FUNDO,
    )
    bbox_header = draw.textbbox((MARGEM_X, cursor_y), header, font=fontes["label"])
    cursor_y = bbox_header[3] + ESPACAMENTO

    # Separador
    draw.line(
        [(MARGEM_X, cursor_y), (CARD_WIDTH - MARGEM_X, cursor_y)],
        fill=COR_SEPARADOR,
        width=2,
    )
    cursor_y += ESPACAMENTO + 8

    # ── Título do produto ────────────────────────────────────────────
    titulo = deal.get("title", "Oferta Especial")
    linhas_titulo = _quebrar_texto(titulo, fontes["titulo"], area_largura, draw)
    # Limitar a 4 linhas para não ultrapassar o card
    linhas_titulo = linhas_titulo[:4]

    for linha in linhas_titulo:
        draw.text(
            (MARGEM_X, cursor_y),
            linha,
            font=fontes["titulo"],
            fill=COR_TITULO,
        )
        bbox_linha = draw.textbbox((MARGEM_X, cursor_y), linha, font=fontes["titulo"])
        cursor_y = bbox_linha[3] + 8

    cursor_y += ESPACAMENTO

    # ── Separador ────────────────────────────────────────────────────
    draw.line(
        [(MARGEM_X, cursor_y), (CARD_WIDTH - MARGEM_X, cursor_y)],
        fill=COR_SEPARADOR,
        width=2,
    )
    cursor_y += ESPACAMENTO + 12

    # ── Preço original (riscado) ─────────────────────────────────────
    preco_original = deal.get("price_original")
    if preco_original:
        label_de = "De: "
        draw.text(
            (MARGEM_X, cursor_y),
            label_de,
            font=fontes["preco_original"],
            fill=COR_PRECO_ORIGINAL,
        )
        bbox_label = draw.textbbox(
            (MARGEM_X, cursor_y), label_de, font=fontes["preco_original"]
        )
        x_preco_orig = bbox_label[2]

        preco_orig_str = _formatar_preco(preco_original)
        _desenhar_riscado(
            draw,
            (x_preco_orig, cursor_y),
            preco_orig_str,
            fontes["preco_original"],
            COR_PRECO_ORIGINAL,
        )
        bbox_orig = draw.textbbox(
            (MARGEM_X, cursor_y), label_de + preco_orig_str, font=fontes["preco_original"]
        )
        cursor_y = bbox_orig[3] + ESPACAMENTO

    # ── Preço atual (destaque verde) ─────────────────────────────────
    preco = deal.get("price")
    if preco:
        label_por = "Por: "
        draw.text(
            (MARGEM_X, cursor_y),
            label_por,
            font=fontes["label"],
            fill=COR_SUBTITULO,
        )
        bbox_por = draw.textbbox(
            (MARGEM_X, cursor_y), label_por, font=fontes["label"]
        )

        preco_str = _formatar_preco(preco)
        # Centralizar verticalmente o texto grande com o label
        y_preco = cursor_y - 18  # Ajuste para alinhar com o label menor
        draw.text(
            (bbox_por[2] + 4, y_preco),
            preco_str,
            font=fontes["preco_atual"],
            fill=COR_PRECO_ATUAL,
        )
        bbox_preco = draw.textbbox(
            (bbox_por[2] + 4, y_preco), preco_str, font=fontes["preco_atual"]
        )
        cursor_y = bbox_preco[3] + ESPACAMENTO + 8
    else:
        # Se não tem preço, mostrar texto genérico
        draw.text(
            (MARGEM_X, cursor_y),
            "Confira o preço no link!",
            font=fontes["preco_atual"],
            fill=COR_PRECO_ATUAL,
        )
        bbox_gen = draw.textbbox(
            (MARGEM_X, cursor_y),
            "Confira o preço no link!",
            font=fontes["preco_atual"],
        )
        cursor_y = bbox_gen[3] + ESPACAMENTO + 8

    # ── Badge de desconto ────────────────────────────────────────────
    desconto = deal.get("discount_pct")
    if desconto and desconto > 0:
        badge_texto = f"-{int(desconto)}% OFF"
        bbox_badge_text = draw.textbbox((0, 0), badge_texto, font=fontes["badge"])
        badge_w = bbox_badge_text[2] - bbox_badge_text[0] + 40
        badge_h = bbox_badge_text[3] - bbox_badge_text[1] + 24

        badge_x = MARGEM_X
        badge_y = cursor_y

        # Retângulo arredondado (usando rectangle simples + bordas)
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=12,
            fill=COR_BADGE_FUNDO,
        )
        # Texto centralizado no badge
        text_x = badge_x + (badge_w - (bbox_badge_text[2] - bbox_badge_text[0])) // 2
        text_y = badge_y + (badge_h - (bbox_badge_text[3] - bbox_badge_text[1])) // 2
        draw.text(
            (text_x, text_y),
            badge_texto,
            font=fontes["badge"],
            fill=COR_BADGE_TEXTO,
        )
        cursor_y = badge_y + badge_h + ESPACAMENTO + 8

    # ── Separador final ──────────────────────────────────────────────
    draw.line(
        [(MARGEM_X, cursor_y), (CARD_WIDTH - MARGEM_X, cursor_y)],
        fill=COR_SEPARADOR,
        width=2,
    )
    cursor_y += ESPACAMENTO + 8

    # ── Nome da loja ─────────────────────────────────────────────────
    loja = deal.get("store")
    if loja:
        loja_texto = f"🏪 {loja}"
        draw.text(
            (MARGEM_X, cursor_y),
            loja_texto,
            font=fontes["loja"],
            fill=COR_LOJA,
        )
        bbox_loja = draw.textbbox((MARGEM_X, cursor_y), loja_texto, font=fontes["loja"])
        cursor_y = bbox_loja[3] + ESPACAMENTO

    # ── Rodapé (marca d'água) ────────────────────────────────────────
    rodape = "📢 Canal de Achadinhos • As melhores ofertas pra você!"
    bbox_rodape = draw.textbbox((0, 0), rodape, font=fontes["rodape"])
    rodape_w = bbox_rodape[2] - bbox_rodape[0]
    rodape_x = (CARD_WIDTH - rodape_w) // 2
    rodape_y = CARD_HEIGHT - MARGEM_Y

    # Linha separadora do rodapé
    draw.line(
        [(MARGEM_X, rodape_y - 16), (CARD_WIDTH - MARGEM_X, rodape_y - 16)],
        fill=COR_SEPARADOR,
        width=1,
    )
    draw.text(
        (rodape_x, rodape_y),
        rodape,
        font=fontes["rodape"],
        fill=COR_RODAPE,
    )

    # ── Exportar como PNG em bytes ───────────────────────────────────
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    png_bytes = buffer.getvalue()

    logger.info(
        "Card gerado: %dx%d, %d bytes — %s",
        CARD_WIDTH,
        CARD_HEIGHT,
        len(png_bytes),
        deal.get("title", "???")[:50],
    )
    return png_bytes
