/**
 * Cliente da API do backend (FastAPI) — Achadinhos.
 *
 * Em dev, a API roda em http://localhost:8000 (ver docker-compose.yml /
 * `uvicorn api.main:app`). Configurável via NEXT_PUBLIC_API_URL.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DealSort = "newest" | "discount" | "price_asc" | "price_desc";

export interface Deal {
  id: string;
  title: string;
  description: string | null;
  price: number | null;
  price_original: number | null;
  discount_pct: number | null;
  url: string | null;
  image_url: string | null;
  store: string | null;
  source: string | null;
  quality_score: number | null;
  created_at: string;
}

export interface DealListResponse {
  total: number;
  results: Deal[];
  limit: number;
  offset: number;
}

export interface DealFilters {
  q?: string;
  store?: string;
  minDiscount?: number;
  sortBy?: DealSort;
  limit?: number;
  offset?: number;
}

/**
 * Busca achadinhos na API, com filtros opcionais de texto, loja,
 * desconto mínimo e ordenação.
 */
export async function fetchDeals(
  filters: DealFilters = {},
  signal?: AbortSignal
): Promise<DealListResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.store) params.set("store", filters.store);
  if (filters.minDiscount != null)
    params.set("min_discount", String(filters.minDiscount));
  params.set("sort_by", filters.sortBy ?? "newest");
  params.set("limit", String(filters.limit ?? 24));
  params.set("offset", String(filters.offset ?? 0));

  const res = await fetch(`${API_URL}/api/deals?${params.toString()}`, {
    signal,
  });

  if (!res.ok) {
    throw new Error(`Falha ao buscar achadinhos (HTTP ${res.status})`);
  }

  return res.json();
}
