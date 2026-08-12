"""
Publisher de ofertas para o Twitter/X via automação de navegador (Playwright).

⚠️  ATENÇÃO — ISTO NÃO USA A API OFICIAL DO X.

A API oficial de escrita do X exige um plano pago para publicar de forma
automatizada. Por decisão explícita do usuário (ciente do risco), este
módulo simula uma pessoa logada normalmente no site via navegador headless
e clica nos mesmos botões que um usuário humano clicaria.

Isso **viola os Termos de Uso do X** e pode resultar em suspensão ou
banimento permanente da conta a qualquer momento — o X pode detectar esse
tipo de automação por padrão de comportamento, mesmo sem usar a API.

Mitigações aplicadas (não eliminam o risco, só reduzem):
- A sessão logada é persistida em disco (cookies) e reaproveitada entre
  execuções, evitando logins repetidos (forte sinal de bot).
- Um único navegador é reaproveitado durante toda a execução do pipeline,
  em vez de abrir um novo a cada oferta.
- NÃO tenta contornar captcha nem verificação em duas etapas — se o X
  pedir isso, a publicação falha e fica registrada no log para você
  resolver manualmente (fazer login uma vez pelo VNC/navegador local).

Se a conta tiver verificação em duas etapas (2FA) ativada, o login
automático provavelmente vai falhar — desative o 2FA nesta conta ou faça
o primeiro login manualmente para gerar o arquivo de sessão.
"""

import logging
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from core.config import get_settings

logger = logging.getLogger(__name__)

# Arquivo de sessão (cookies) — persistido via volume Docker (ver docker-compose.yml)
STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "twitter_state.json"

LOGIN_URL = "https://x.com/i/flow/login"
HOME_URL = "https://x.com/home"
TWEET_MAX_LEN = 280
_TIMEOUT_MS = 20_000

# Estado global do módulo (reaproveitado durante todo o pipeline)
_playwright: Playwright | None = None
_browser: Browser | None = None
_context: BrowserContext | None = None


def _formatar_preco_br(valor: float | None) -> str:
    if valor is None:
        return ""
    inteiro = int(valor)
    decimal = int(round((valor - inteiro) * 100))
    inteiro_str = f"{inteiro:,}".replace(",", ".")
    return f"R$ {inteiro_str},{decimal:02d}"


def _montar_texto(deal: dict[str, Any]) -> str:
    """Monta o texto do tweet, respeitando o limite de 280 caracteres."""
    titulo = deal.get("title") or "Oferta especial"
    preco = deal.get("price")
    desconto = deal.get("discount_pct")
    url = deal.get("affiliate_url") or deal.get("url") or ""

    linhas = [f"🔥 {titulo}"]
    if preco:
        linhas.append(f"💰 {_formatar_preco_br(preco)}")
    if desconto and desconto > 0:
        linhas.append(f"📉 -{int(desconto)}% OFF")
    linhas.append(url)

    texto = "\n".join(linhas)
    if len(texto) <= TWEET_MAX_LEN:
        return texto

    # Corta o título até caber, mantendo preço/desconto/link intactos
    resto = "\n".join(linhas[1:])
    espaco_titulo = TWEET_MAX_LEN - len(resto) - len("🔥 ") - len("\n") - 1
    titulo_cortado = titulo[: max(espaco_titulo, 10)].rstrip() + "…"
    linhas[0] = f"🔥 {titulo_cortado}"
    return "\n".join(linhas)[:TWEET_MAX_LEN]


async def _esta_logado(page: Page) -> bool:
    """Verifica se a sessão atual já está autenticada."""
    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=_TIMEOUT_MS)
        await page.wait_for_selector(
            '[data-testid="SideNav_NewTweet_Button"], [data-testid="tweetTextarea_0"]',
            timeout=8_000,
        )
        return True
    except PlaywrightTimeoutError:
        return False


async def _fazer_login(page: Page) -> bool:
    """
    Executa o fluxo de login manual (usuário + senha).

    Retorna False (sem lançar exceção) se o X pedir verificação adicional
    (captcha, 2FA, confirmação de telefone/email) — esses fluxos não são
    automatizados de propósito.
    """
    settings = get_settings()

    if not settings.twitter_username or not settings.twitter_password:
        logger.warning(
            "Twitter: TWITTER_USERNAME/TWITTER_PASSWORD não configurados. "
            "Pulando publicação."
        )
        return False

    try:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=_TIMEOUT_MS)

        campo_usuario = page.get_by_label("Phone, email, or username").or_(
            page.locator('input[autocomplete="username"]')
        )
        await campo_usuario.fill(settings.twitter_username, timeout=_TIMEOUT_MS)
        await page.get_by_role("button", name="Next").click(timeout=_TIMEOUT_MS)

        # X às vezes pede confirmação extra de usuário/telefone antes da senha —
        # se aparecer, não sabemos preencher automaticamente.
        campo_senha = page.locator('input[name="password"]')
        try:
            await campo_senha.wait_for(timeout=6_000)
        except PlaywrightTimeoutError:
            logger.error(
                "Twitter: X pediu verificação adicional antes da senha "
                "(provavelmente confirmação de telefone/email). Login "
                "automático não pode continuar — faça login manual uma vez "
                "para liberar a conta."
            )
            return False

        await campo_senha.fill(settings.twitter_password, timeout=_TIMEOUT_MS)
        await page.get_by_role("button", name="Log in").click(timeout=_TIMEOUT_MS)

        # Aguarda navegação pra home OU detecta pedido de 2FA/verificação
        try:
            await page.wait_for_url(f"{HOME_URL}*", timeout=_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.error(
                "Twitter: login não completou automaticamente (provável "
                "verificação em duas etapas ou captcha). Desative o 2FA "
                "nesta conta ou faça login manual uma vez para gerar a "
                "sessão em %s.",
                STATE_PATH,
            )
            return False

        logger.info("Twitter: login realizado com sucesso.")
        return True

    except PlaywrightTimeoutError as exc:
        logger.error("Twitter: timeout durante o login — %s", exc)
        return False


async def init_twitter() -> bool:
    """
    Inicializa o navegador e garante uma sessão logada, reaproveitando
    cookies salvos em disco quando possível.

    Deve ser chamado uma vez no início do pipeline (não por oferta).

    Returns:
        True se pronto para publicar, False se desabilitado ou falhou.
    """
    global _playwright, _browser, _context

    settings = get_settings()
    if not settings.twitter_enabled:
        return False

    try:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)

        state = str(STATE_PATH) if STATE_PATH.exists() else None
        _context = await _browser.new_context(storage_state=state)

        page = await _context.new_page()
        logado = await _esta_logado(page)

        if not logado:
            logado = await _fazer_login(page)
            if logado:
                STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                await _context.storage_state(path=str(STATE_PATH))

        await page.close()

        if not logado:
            await fechar_twitter()
            return False

        return True

    except Exception as exc:
        logger.error("Twitter: falha ao inicializar navegador — %s", exc, exc_info=True)
        await fechar_twitter()
        return False


async def publicar_no_twitter(deal: dict[str, Any], card_image: bytes) -> bool:
    """
    Publica uma oferta como tweet com imagem.

    Requer que `init_twitter()` já tenha sido chamado com sucesso nesta
    execução do pipeline.

    Args:
        deal: Dicionário com dados da oferta.
        card_image: Bytes do PNG do card gerado.

    Returns:
        True se publicado com sucesso, False caso contrário.
    """
    if _context is None:
        logger.warning("Twitter: sessão não inicializada. Pulando publicação.")
        return False

    titulo = deal.get("title", "???")[:60]
    page = await _context.new_page()

    try:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=_TIMEOUT_MS)

        caixa_texto = page.locator('[data-testid="tweetTextarea_0"]')
        await caixa_texto.click(timeout=_TIMEOUT_MS)
        await caixa_texto.fill(_montar_texto(deal))

        input_arquivo = page.locator('input[data-testid="fileInput"]')
        await input_arquivo.set_input_files(
            files=[{"name": "achadinho.png", "mimeType": "image/png", "buffer": card_image}]
        )
        # Aguarda a prévia da imagem renderizar antes de postar
        await page.wait_for_selector('[data-testid="attachments"]', timeout=_TIMEOUT_MS)

        botao_postar = page.locator('[data-testid="tweetButtonInline"]')
        await botao_postar.click(timeout=_TIMEOUT_MS)

        # Confirma que o compositor fechou (sinal de que o post foi enviado)
        await caixa_texto.wait_for(state="hidden", timeout=_TIMEOUT_MS)

        logger.info("Tweet publicado com sucesso: %s", titulo)
        return True

    except PlaywrightTimeoutError as exc:
        logger.error("Twitter: falha ao publicar tweet '%s' — %s", titulo, exc)
        return False
    except Exception as exc:
        logger.error(
            "Twitter: erro inesperado ao publicar '%s' — %s", titulo, exc, exc_info=True
        )
        return False
    finally:
        await page.close()


async def fechar_twitter() -> None:
    """Fecha o navegador e libera os recursos do Playwright."""
    global _playwright, _browser, _context

    if _context is not None:
        await _context.close()
        _context = None
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None
