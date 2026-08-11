"""
Utilitários compartilhados entre os scrapers de ofertas.
"""

import re


def converter_preco_br(texto: str | int | float | None) -> float | None:
    """
    Converte um preço no formato brasileiro para float.

    Aceita tanto strings ('1.299,90', '270', '5.427') quanto
    números já convertidos (int/float), retornando sempre float.

    Exemplos:
        '1.299,90' → 1299.90
        '270'      → 270.0
        '5.427'    → 5427.0

    Args:
        texto: Preço em formato string (BR) ou numérico.

    Returns:
        Valor float ou None se inválido.
    """
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto) if texto > 0 else None

    limpo = texto.strip()
    if not limpo:
        return None

    try:
        if "," in limpo:
            # Tem separador decimal: remove milhar (.) e troca decimal (,) por (.)
            limpo = limpo.replace(".", "").replace(",", ".")
        else:
            # Sem separador decimal: os pontos são apenas milhar
            limpo = limpo.replace(".", "")
        valor = float(limpo)
        return valor if valor > 0 else None
    except ValueError:
        return None


def limpar_html(texto: str | None) -> str:
    """
    Remove tags HTML e entidades comuns de um texto.

    Args:
        texto: Texto com possível HTML.

    Returns:
        Texto limpo (string vazia se `texto` for None/vazio).
    """
    if not texto:
        return ""
    limpo = re.sub(r"<[^>]+>", " ", texto)
    limpo = (
        limpo.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", limpo).strip()


def calcular_quality_score(
    discount_pct: float | None,
    sinal_popularidade: float = 0.0,
) -> float:
    """
    Calcula um score simples de qualidade (0-100) para priorização futura.

    Combina o percentual de desconto (peso principal) com um sinal de
    popularidade da fonte (temperatura no Pelando, curtidas no Promobit),
    normalizado e limitado a 100.

    Args:
        discount_pct: Percentual de desconto, se conhecido.
        sinal_popularidade: Sinal bruto de popularidade (já normalizado 0-100
            pelo chamador).

    Returns:
        Score entre 0 e 100.
    """
    base = discount_pct or 0.0
    score = base * 0.8 + min(sinal_popularidade, 100.0) * 0.2
    return round(min(max(score, 0.0), 100.0), 2)
