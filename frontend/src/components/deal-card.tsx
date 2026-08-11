import Image from "next/image";
import { ExternalLink, Store as StoreIcon } from "lucide-react";

import type { Deal } from "@/lib/api";
import { formatBRL, formatRelativeTime } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/** Paleta cíclica usada no fundo do placeholder quando não há imagem. */
const PLACEHOLDER_GRADIENTS = [
  "from-orange-500 to-rose-500",
  "from-sky-500 to-indigo-500",
  "from-emerald-500 to-teal-500",
  "from-fuchsia-500 to-purple-500",
  "from-amber-500 to-orange-600",
];

function gradientFor(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  return PLACEHOLDER_GRADIENTS[hash % PLACEHOLDER_GRADIENTS.length];
}

export function DealCard({ deal }: { deal: Deal }) {
  const hasDiscount = !!deal.discount_pct && deal.discount_pct > 0;

  return (
    <Card className="group overflow-hidden gap-3 py-0 transition-shadow hover:shadow-md">
      <div className="relative aspect-square w-full overflow-hidden bg-muted">
        {deal.image_url ? (
          <Image
            src={deal.image_url}
            alt={deal.title}
            fill
            sizes="(min-width: 1024px) 240px, 45vw"
            className="object-contain p-4 transition-transform group-hover:scale-105"
            unoptimized
          />
        ) : (
          <div
            className={`flex h-full w-full items-center justify-center bg-gradient-to-br ${gradientFor(
              deal.store ?? deal.title
            )} text-white`}
          >
            <StoreIcon className="size-10 opacity-80" />
          </div>
        )}

        {hasDiscount && (
          <Badge
            variant="destructive"
            className="absolute top-2 left-2 bg-red-600 text-white"
          >
            -{Math.round(deal.discount_pct!)}%
          </Badge>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 px-3 pb-3">
        <p className="line-clamp-2 min-h-10 text-sm font-medium leading-tight">
          {deal.title}
        </p>

        <div className="flex items-baseline gap-2">
          <span className="text-lg font-bold text-emerald-600 dark:text-emerald-400">
            {formatBRL(deal.price)}
          </span>
          {deal.price_original && deal.price_original > (deal.price ?? 0) && (
            <span className="text-xs text-muted-foreground line-through">
              {formatBRL(deal.price_original)}
            </span>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          {deal.store && (
            <Badge variant="secondary" className="max-w-[60%] truncate">
              {deal.store}
            </Badge>
          )}
          <span className="shrink-0">{formatRelativeTime(deal.created_at)}</span>
        </div>

        <Button
          size="sm"
          className="mt-1 w-full"
          nativeButton={false}
          render={
            <a
              href={deal.url ?? "#"}
              target="_blank"
              rel="noopener noreferrer sponsored"
            />
          }
        >
          Comprar agora
          <ExternalLink data-icon="inline-end" />
        </Button>
      </div>
    </Card>
  );
}
