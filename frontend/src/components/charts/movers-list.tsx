import Link from "next/link";
import type { RankingItem } from "@/lib/api/types";
import { DeltaPill } from "@/components/ui/delta-pill";
import { formatEuro } from "@/lib/format-fr";

// Liste de variations de prix (hausses ou baisses). Server component :
// les valeurs sont visibles en clair (prix avant → après + delta signé),
// la couleur n'est qu'un renfort.
//
// Nom du produit résolu contre Cloud SQL `products`. Un EAN hors catalogue
// (`in_catalog=false`) n'est jamais affiché nu : on le montre ACCOMPAGNÉ de
// son prix, de son code et d'une mention « Non référencé ». Le clic aboutit
// toujours — la fiche « prix seulement » absorbe les EAN sans fiche.
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
        const named = !!item.produit_nom;
        const label = item.produit_nom ?? "Produit non référencé";
        const hasPrices =
          item.price_eur_previous != null && item.price_eur_current != null;

        const inner = (
          <div className="flex items-center gap-3 py-3">
            <span className="w-4 shrink-0 text-center text-xs font-medium tabular-nums text-dark-5 dark:text-dark-6">
              {i + 1}
            </span>

            {item.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={item.image_url}
                alt=""
                className="size-10 shrink-0 rounded-lg border border-stroke bg-white object-contain dark:border-dark-3"
              />
            ) : (
              <span
                aria-hidden
                className="grid size-10 shrink-0 place-items-center rounded-lg bg-gray-1 text-xs font-semibold text-dark-5 dark:bg-dark-2 dark:text-dark-6"
              >
                {named ? item.produit_nom!.charAt(0).toUpperCase() : "#"}
              </span>
            )}

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-dark dark:text-white">
                  {label}
                </span>
                {!item.in_catalog && (
                  <span className="shrink-0 rounded-full bg-gray-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-dark-5 dark:bg-dark-2 dark:text-dark-6">
                    Non référencé
                  </span>
                )}
              </div>
              <div className="truncate text-xs text-dark-5 dark:text-dark-6">
                {item.brand && <span>{item.brand} · </span>}
                {hasPrices ? (
                  <span style={{ fontVariantNumeric: "tabular-nums" }}>
                    {formatEuro(item.price_eur_previous!)} →{" "}
                    {formatEuro(item.price_eur_current!)}
                  </span>
                ) : (
                  <span>prix médian relevé</span>
                )}
                {item.sample_size != null && (
                  <span className="opacity-70"> · {item.sample_size} relevés</span>
                )}
                {!named && item.ean && (
                  <span className="opacity-70"> · réf. {item.ean}</span>
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
