import Link from "next/link";
import type { EnseigneProductRank } from "@/lib/api/types";
import { DeltaPill } from "@/components/ui/delta-pill";
import { formatEuro } from "@/lib/format-fr";

// Liste des produits sur lesquels une enseigne se situe (moins / plus chère que
// la médiane inter-enseignes). Server component : prix enseigne + prix de
// référence en clair, l'écart signé porté par DeltaPill (la couleur n'est qu'un
// renfort). Un EAN hors catalogue (`in_catalog=false`) n'est jamais nu : nom
// remplacé par « Produit non référencé », accompagné de son prix et de son code.
// Le clic aboutit toujours (la fiche produit absorbe les EAN « prix seulement »).
export function ProductRankList({
  items,
  emptyMessage,
}: {
  items: EnseigneProductRank[];
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

        const inner = (
          <div className="flex items-center gap-3 py-3">
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
                <span style={{ fontVariantNumeric: "tabular-nums" }}>
                  {item.price_eur != null ? formatEuro(item.price_eur) : "—"}
                  {item.ref_price_eur != null && (
                    <span className="opacity-70">
                      {" "}
                      (médiane {formatEuro(item.ref_price_eur)})
                    </span>
                  )}
                </span>
                {!named && item.ean && (
                  <span className="opacity-70"> · réf. {item.ean}</span>
                )}
              </div>
            </div>

            <DeltaPill pct={item.delta_pct} />
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
