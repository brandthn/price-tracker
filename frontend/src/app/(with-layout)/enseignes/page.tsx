import Link from "next/link";
import { getEnseignes } from "@/lib/api/enseignes";
import type { EnseignesOut, EnseigneSummary } from "@/lib/api/types";
import { CherteBar } from "@/components/enseignes/cherte-bar";
import { formatNumber } from "@/lib/format-fr";

export const dynamic = "force-dynamic";

// Comparateur d'enseignes : « chez qui payez-vous le moins cher ? ». Un seul
// chiffre, honnête : l'indice de cherté relative (à produits identiques, il
// neutralise les différences d'assortiment). Les enseignes sous le seuil de
// couverture restent listées mais sans indice (transparence).
export default async function EnseignesPage() {
  let data: EnseignesOut | null = null;
  try {
    data = await getEnseignes();
  } catch {
    data = null;
  }

  const ranked = (data?.items ?? []).filter((it) => it.cherte_index != null);
  const uncovered = (data?.items ?? []).filter((it) => it.cherte_index == null);

  return (
    <>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-heading-5 font-bold text-dark dark:text-white sm:text-heading-4">
            Enseignes
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-dark-5 dark:text-dark-6">
            Chez qui payez-vous le moins cher ? Comparaison à produits identiques
            — le même produit d&apos;une enseigne à l&apos;autre — sur les{" "}
            {data?.window_weeks ?? 12} dernières semaines.
          </p>
        </div>
        <Link
          href="/tickets/upload"
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90"
        >
          <span aria-hidden>+</span> Ajouter un ticket
        </Link>
      </div>

      {data == null && (
        <div className="rounded-2xl border border-red-light bg-red-light-6 p-5 text-sm text-red dark:border-red-dark dark:bg-red/10">
          Le comparateur est momentanément indisponible. Réessayez dans quelques
          instants — vos données ne sont pas perdues.
        </div>
      )}

      {data != null && ranked.length === 0 && uncovered.length === 0 && (
        <div className="rounded-2xl border border-dashed border-stroke bg-gray-1 p-6 text-sm text-dark-5 dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6">
          Le comparateur se construit : il faut qu&apos;un même produit soit relevé
          dans plusieurs enseignes pour les comparer. Ajoutez des tickets pour
          couvrir plus d&apos;enseignes.
        </div>
      )}

      {data != null && (ranked.length > 0 || uncovered.length > 0) && (
        <section className="rounded-2xl border border-stroke bg-white p-4 dark:border-dark-3 dark:bg-gray-dark sm:p-6">
          <div className="mb-4 flex flex-col gap-1 border-b border-stroke pb-4 dark:border-dark-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-dark-5 dark:text-dark-6">
              Indice 100 = niveau médian des enseignes. Calculé sur les produits
              relevés dans au moins deux enseignes.
            </p>
            <div className="flex items-center gap-2 text-[11px] font-medium text-dark-5 dark:text-dark-6">
              <span style={{ color: "var(--viz-down-text)" }}>◀ moins chère</span>
              <span className="opacity-50">|</span>
              <span style={{ color: "var(--viz-up-text)" }}>plus chère ▶</span>
            </div>
          </div>

          <ul className="flex flex-col gap-1">
            {ranked.map((it) => (
              <EnseigneRow key={it.enseigne} item={it} />
            ))}
          </ul>

          {uncovered.length > 0 && (
            <div className="mt-5 border-t border-stroke pt-4 dark:border-dark-3">
              <p className="mb-2 text-xs text-dark-5 dark:text-dark-6">
                Relevées, mais pas encore assez de produits comparés pour un indice
                fiable :
              </p>
              <div className="flex flex-wrap gap-2">
                {uncovered.map((it) => (
                  <Link
                    key={it.enseigne}
                    href={`/enseignes/${encodeURIComponent(it.enseigne)}`}
                    className="inline-flex items-center gap-1.5 rounded-full border border-stroke bg-gray-1 px-3 py-1 text-xs text-dark-4 hover:border-primary hover:text-primary dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6"
                  >
                    {it.enseigne}
                    <span className="tabular-nums opacity-60">
                      · {it.matched_products}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </>
  );
}

function EnseigneRow({ item }: { item: EnseigneSummary }) {
  const index = item.cherte_index!;
  const delta = Math.round(index - 100);
  const deltaLabel =
    Math.abs(index - 100) < 0.5
      ? "au niveau médian"
      : delta > 0
        ? `+${delta} % vs médiane`
        : `${delta} % vs médiane`;

  return (
    <li>
      <Link
        href={`/enseignes/${encodeURIComponent(item.enseigne)}`}
        className="block rounded-xl px-2 py-3 hover:bg-gray-1 dark:hover:bg-dark-2 sm:px-3"
      >
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1 sm:flex-none sm:w-48">
            <div className="truncate text-sm font-semibold text-dark dark:text-white">
              {item.enseigne}
            </div>
            <div className="text-xs text-dark-5 dark:text-dark-6">
              {formatNumber(item.matched_products)} produits comparés
            </div>
          </div>

          <div className="hidden min-w-0 flex-1 sm:block">
            <CherteBar index={index} />
          </div>

          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <div className="text-right">
              <div className="text-base font-bold tabular-nums text-dark dark:text-white">
                {Math.round(index)}
              </div>
              <div className="text-[11px] tabular-nums text-dark-5 dark:text-dark-6">
                {deltaLabel}
              </div>
            </div>
            <ChevronRight />
          </div>
        </div>

        {/* Barre pleine largeur sous la ligne en mobile (le tableau ne scrolle pas). */}
        <div className="mt-2 sm:hidden">
          <CherteBar index={index} />
        </div>
      </Link>
    </li>
  );
}

function ChevronRight() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      className="shrink-0 text-dark-5 dark:text-dark-6"
    >
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}
