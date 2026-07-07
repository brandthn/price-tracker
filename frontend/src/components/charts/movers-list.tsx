import Link from "next/link";
import type { RankingItem } from "@/lib/api/types";
import { DeltaPill } from "@/components/ui/delta-pill";
import { formatEuro } from "@/lib/format-fr";

// Liste de variations de prix (hausses ou baisses). Server component :
// les valeurs sont visibles en clair (prix avant → après + delta signé),
// la couleur n'est qu'un renfort.
export function MoversList({
  items,
  emptyMessage,
}: {
  items: RankingItem[];
  emptyMessage: string;
}) {
  if (items.length === 0) {
    return (
      <p className="px-1 py-6 text-sm text-dark-5 dark:text-dark-6">
        {emptyMessage}
      </p>
    );
  }

  return (
    <ul className="divide-y divide-stroke dark:divide-dark-3">
      {items.map((item, i) => {
        const label = item.produit_nom ?? item.ean ?? "Produit inconnu";
        const inner = (
          <div className="flex items-center gap-3 py-3">
            <span className="w-5 shrink-0 text-center text-xs font-medium text-dark-5 dark:text-dark-6">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-dark dark:text-white">
                {label}
              </div>
              <div className="truncate text-xs text-dark-5 dark:text-dark-6">
                {item.brand && <span>{item.brand} · </span>}
                {item.price_eur_previous != null &&
                item.price_eur_current != null ? (
                  <span style={{ fontVariantNumeric: "tabular-nums" }}>
                    {formatEuro(item.price_eur_previous)} →{" "}
                    {formatEuro(item.price_eur_current)}
                  </span>
                ) : (
                  <span>prix médian relevé</span>
                )}
                {item.sample_size != null && (
                  <span className="opacity-70"> · {item.sample_size} relevés</span>
                )}
              </div>
            </div>
            <DeltaPill pct={item.pct_change} />
          </div>
        );

        return (
          <li key={`${item.ean ?? label}-${i}`}>
            {item.ean ? (
              <Link
                href={`/products/${item.ean}`}
                className="block rounded-lg px-1 hover:bg-gray-1 dark:hover:bg-dark-2"
              >
                {inner}
              </Link>
            ) : (
              <div className="px-1">{inner}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
