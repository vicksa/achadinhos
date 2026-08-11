"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Flame, SlidersHorizontal } from "lucide-react";

import { fetchDeals, type DealSort } from "@/lib/api";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DealCard } from "@/components/deal-card";

const SORT_OPTIONS: { value: DealSort; label: string }[] = [
  { value: "newest", label: "Mais recentes" },
  { value: "discount", label: "Maior desconto" },
  { value: "price_asc", label: "Menor preço" },
  { value: "price_desc", label: "Maior preço" },
];

export default function Home() {
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<DealSort>("newest");
  const [onlyDiscount, setOnlyDiscount] = useState(false);
  const debouncedSearch = useDebouncedValue(search, 350);

  const filters = useMemo(
    () => ({
      q: debouncedSearch || undefined,
      sortBy,
      minDiscount: onlyDiscount ? 1 : undefined,
      limit: 24,
    }),
    [debouncedSearch, sortBy, onlyDiscount]
  );

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["deals", filters],
    queryFn: ({ signal }) => fetchDeals(filters, signal),
    placeholderData: (previous) => previous,
  });

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <Header />

      <SearchArea
        search={search}
        onSearchChange={setSearch}
        sortBy={sortBy}
        onSortChange={setSortBy}
        onlyDiscount={onlyDiscount}
        onOnlyDiscountChange={setOnlyDiscount}
        total={data?.total}
        isFetching={isFetching}
      />

      {isError && (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          Não foi possível carregar os achadinhos agora. Confira se a API
          está rodando (`docker compose up -d` na raiz do projeto).
        </p>
      )}

      {isLoading ? (
        <ResultsGridSkeleton />
      ) : data && data.results.length > 0 ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {data.results.map((deal) => (
            <DealCard key={deal.id} deal={deal} />
          ))}
        </div>
      ) : (
        !isError && (
          <p className="py-16 text-center text-sm text-muted-foreground">
            Nenhum achadinho encontrado{search ? ` para "${search}"` : ""}.
          </p>
        )
      )}
    </div>
  );
}

function Header() {
  return (
    <header className="flex flex-col items-center gap-2 text-center">
      <div className="flex items-center gap-2 text-2xl font-bold tracking-tight sm:text-3xl">
        <Flame className="size-7 text-orange-500" />
        Achadinhos
      </div>
      <p className="max-w-md text-sm text-muted-foreground">
        Os melhores preços e descontos de e-commerce, coletados automaticamente
        e postados no nosso canal do Telegram.
      </p>
    </header>
  );
}

function SearchArea({
  search,
  onSearchChange,
  sortBy,
  onSortChange,
  onlyDiscount,
  onOnlyDiscountChange,
  total,
  isFetching,
}: {
  search: string;
  onSearchChange: (v: string) => void;
  sortBy: DealSort;
  onSortChange: (v: DealSort) => void;
  onlyDiscount: boolean;
  onOnlyDiscountChange: (v: boolean) => void;
  total: number | undefined;
  isFetching: boolean;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center">
      <div className="relative flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Buscar achadinho — ex: tênis, iphone, air fryer..."
          className="h-10 pl-9"
        />
      </div>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant={onlyDiscount ? "default" : "outline"}
          onClick={() => onOnlyDiscountChange(!onlyDiscount)}
        >
          <SlidersHorizontal data-icon="inline-start" />
          Com desconto
        </Button>

        <select
          value={sortBy}
          onChange={(e) => onSortChange(e.target.value as DealSort)}
          className="h-8 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {total != null && (
        <span className="shrink-0 text-xs text-muted-foreground">
          {total} achadinho{total === 1 ? "" : "s"}
          {isFetching ? "…" : ""}
        </span>
      )}
    </div>
  );
}

function ResultsGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="flex flex-col gap-2">
          <Skeleton className="aspect-square w-full rounded-xl" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ))}
    </div>
  );
}
