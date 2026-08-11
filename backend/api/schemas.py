"""
Schemas Pydantic v2 para a API de Agregação de Preços.

Define os modelos de request/response utilizados nos endpoints de busca,
garantindo validação, serialização e documentação automática via OpenAPI.
"""

from pydantic import BaseModel, Field, field_validator
from enum import Enum


class SortOption(str, Enum):
    """Opções de ordenação disponíveis para resultados de busca."""
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    DISCOUNT = "discount"
    RATING = "rating"
    NAME = "name"


class ProductOffer(BaseModel):
    """
    Oferta de produto normalizada de qualquer marketplace.

    Representa um único resultado de busca com preço, imagem, avaliações
    e links (direto e de afiliado) do marketplace de origem.
    """

    name: str = Field(
        ...,
        description="Nome do produto conforme exibido no marketplace.",
        examples=["Fone de Ouvido Bluetooth JBL Tune 520BT"],
    )
    price: float = Field(
        ...,
        gt=0,
        description="Preço atual em BRL.",
        examples=[189.90],
    )
    price_old: float | None = Field(
        default=None,
        gt=0,
        description="Preço anterior (antes do desconto), se disponível.",
        examples=[299.90],
    )
    image_url: str | None = Field(
        default=None,
        description="URL da imagem principal do produto.",
    )
    marketplace: str = Field(
        ...,
        description="Marketplace de origem (ex: mercadolivre, amazon).",
        examples=["mercadolivre"],
    )
    url: str = Field(
        ...,
        description="URL direta da oferta no marketplace.",
    )
    affiliate_url: str | None = Field(
        default=None,
        description="URL de afiliado para monetização, se configurada.",
    )
    rating: float | None = Field(
        default=None,
        ge=0,
        le=5,
        description="Nota média do produto (0-5 estrelas).",
    )
    rating_count: int | None = Field(
        default=None,
        ge=0,
        description="Quantidade de avaliações do produto.",
    )
    in_stock: bool = Field(
        default=True,
        description="Indica se o produto está disponível em estoque.",
    )
    discount_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Percentual de desconto calculado a partir de price_old.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Echo Dot 5ª Geração",
                    "price": 279.00,
                    "price_old": 399.00,
                    "image_url": "https://http2.mlstatic.com/D_NQ_NP_example.webp",
                    "marketplace": "mercadolivre",
                    "url": "https://www.mercadolivre.com.br/echo-dot/p/MLB12345",
                    "affiliate_url": None,
                    "rating": 4.7,
                    "rating_count": 12340,
                    "in_stock": True,
                    "discount_pct": 30.08,
                }
            ]
        }
    }


class SearchResponse(BaseModel):
    """
    Resposta completa de uma busca de preços.

    Contém os resultados normalizados de todos os marketplaces consultados,
    junto com metadados como tempo de busca e indicação de cache.
    """

    query: str = Field(
        ...,
        description="Termo de busca utilizado.",
    )
    total_results: int = Field(
        ...,
        ge=0,
        description="Número total de ofertas encontradas.",
    )
    results: list[ProductOffer] = Field(
        default_factory=list,
        description="Lista de ofertas ordenadas conforme o critério de sort.",
    )
    cached: bool = Field(
        default=False,
        description="True se os resultados foram servidos do cache Redis.",
    )
    search_time_ms: float = Field(
        ...,
        ge=0,
        description="Tempo total da busca em milissegundos.",
    )


class SearchQuery(BaseModel):
    """
    Parâmetros de entrada para uma busca de preços.

    Utilizado como query parameters no endpoint GET /api/search.
    """

    q: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Termo de busca (mínimo 2 caracteres).",
        examples=["iphone 15"],
    )
    sort_by: SortOption = Field(
        default=SortOption.PRICE_ASC,
        description="Critério de ordenação dos resultados.",
    )
    min_price: float | None = Field(
        default=None,
        gt=0,
        description="Filtro de preço mínimo em BRL.",
    )
    max_price: float | None = Field(
        default=None,
        gt=0,
        description="Filtro de preço máximo em BRL.",
    )
    marketplace: str | None = Field(
        default=None,
        description="Filtrar por marketplace específico (ex: mercadolivre).",
    )

    @field_validator("q")
    @classmethod
    def normalizar_query(cls, v: str) -> str:
        """Remove espaços extras e normaliza o termo de busca."""
        return " ".join(v.strip().split())

    @field_validator("max_price")
    @classmethod
    def validar_faixa_preco(cls, v: float | None, info) -> float | None:
        """Garante que max_price >= min_price quando ambos informados."""
        min_price = info.data.get("min_price")
        if v is not None and min_price is not None and v < min_price:
            raise ValueError("max_price deve ser maior ou igual a min_price")
        return v


class SuggestionResponse(BaseModel):
    """Resposta do endpoint de sugestões de busca."""

    suggestions: list[str] = Field(
        default_factory=list,
        description="Lista de termos sugeridos baseados em buscas recentes.",
    )


class DealSortOption(str, Enum):
    """Opções de ordenação disponíveis para a listagem de achadinhos."""
    NEWEST = "newest"
    DISCOUNT = "discount"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"


class DealOut(BaseModel):
    """
    Achadinho (oferta coletada pelo bot) exposto pela API pública.

    Espelha o modelo `Deal` do banco, mas só com os campos relevantes
    para exibição — sem detalhes internos de publicação/pipeline.
    """

    id: str = Field(..., description="ID único do achadinho.")
    title: str = Field(..., description="Título do produto.")
    description: str | None = Field(default=None, description="Descrição breve.")
    price: float | None = Field(default=None, description="Preço atual em BRL.")
    price_original: float | None = Field(
        default=None, description="Preço antes do desconto, se conhecido."
    )
    discount_pct: float | None = Field(
        default=None, description="Percentual de desconto, se conhecido."
    )
    url: str | None = Field(default=None, description="Link direto para comprar.")
    image_url: str | None = Field(default=None, description="URL da imagem do produto.")
    store: str | None = Field(default=None, description="Loja/marketplace da oferta.")
    source: str | None = Field(default=None, description="Fonte que coletou (pelando, promobit).")
    quality_score: float | None = Field(default=None, description="Score de qualidade (0-100).")
    created_at: str = Field(..., description="Data/hora de coleta (ISO 8601).")

    model_config = {"from_attributes": True}


class DealListResponse(BaseModel):
    """Resposta paginada da listagem de achadinhos."""

    total: int = Field(..., ge=0, description="Total de achadinhos disponíveis (após filtros).")
    results: list[DealOut] = Field(default_factory=list)
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)
