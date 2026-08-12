"""
Configuração centralizada da aplicação.
Carrega variáveis do .env via Pydantic Settings.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Configurações globais carregadas do .env"""

    # ---- Ambiente ----
    environment: str = "development"
    log_level: str = "INFO"

    # ---- PostgreSQL ----
    database_url: str = "postgresql+asyncpg://root:password@localhost:5432/achadinhos"

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- Telegram Bot ----
    telegram_bot_token: str = "SEU_TOKEN_AQUI"
    telegram_channel_id: str = "@seucanaldeofertas"

    # ---- Instagram Graph API ----
    meta_app_id: str = ""
    meta_app_secret: str = ""
    instagram_user_id: str = ""
    instagram_access_token: str = ""

    # ---- ImgBB (hospedagem pública das imagens dos cards p/ Instagram) ----
    imgbb_api_key: str = ""

    # ---- Twitter/X (automação via navegador — não usa a API oficial) ----
    twitter_username: str = ""
    twitter_password: str = ""
    twitter_enabled: bool = False

    # ---- Mercado Livre ----
    ml_client_id: str = ""
    ml_client_secret: str = ""

    # ---- Amazon PA-API ----
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""

    # ---- Cache TTLs (segundos) ----
    cache_ttl_mercadolivre: int = 900   # 15 min
    cache_ttl_amazon: int = 1800        # 30 min
    cache_ttl_default: int = 900        # 15 min

    # ---- Bot de Achadinhos ----
    deal_check_interval_minutes: int = 5
    deal_min_discount_pct: float = 15.0
    deal_dedup_ttl_days: int = 7
    telegram_post_cooldown_seconds: int = 120  # 2 min entre posts

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """Singleton cacheado das configurações."""
    return Settings()
