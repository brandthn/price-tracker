import Link from "next/link";
import type { Metadata } from "next";
import { getEnseigneDetail } from "@/lib/api/enseignes";
import type { EnseigneDetailOut } from "@/lib/api/types";
import { DeltaPill } from "@/components/ui/delta-pill";
import { ProductRankList } from "@/components/enseignes/product-rank-list";
import { formatNumber } from "@/lib/format-fr";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ nom: string }>;
}): Promise<Metadata> {
  const { nom } = await params;
  // `nom` est déjà décodé par Next (params de route) → pas de decodeURIComponent.
  return { title: `${nom} — Enseignes` };
}

// Fiche enseigne : positionnement prix (indice de cherté) + les produits sur
// lesquels l'enseigne est la moins / plus chère que la médiane inter-enseignes.
// Enseigne inconnue → écran « non suivie » (le backend renvoie 200 tracked=false,
// jamais un 404).
export default async function EnseigneDetailPage({
  params,
}: {
  params: Promise<{ nom: string }>;
}) {
  const { nom } = await params;
  const data: EnseigneDetailOut = await getEnseigneDetail(nom);

  if (!data.tracked) {
    return (
      <>
        <BackLink />
        <h1 className="mb-4 mt-2 text-heading-5 font-bold text-dark dark:text-white sm:text-heading-4">
          {data.enseigne}
        </h1>
        <div className="rounded-2xl border border-dashed border-stroke bg-gray-1 p-6 text-sm text-dark-5 dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6">
          Cette enseigne n&apos;est pas encore suivie. Elle apparaîtra dès que des
          tickets la concernant seront ajoutés.
          <div className="mt-4">
            <Link href="/enseignes" className="font-semibold text-primary hover:underline">
              Voir toutes les enseignes →
            </Link>
          </div>
        </div>
      </>
    );
  }

  const index = data.cherte_index;
  const hasIndex = index != null;
  const delta = hasIndex ? index! - 100 : 0;
  const positioning = hasIndex ? qualifier(index!) : null;

  return (
    <>
      <BackLink />
      <h1 className="mb-4 mt-2 text-heading-5 font-bold text-dark dark:text-white sm:text-heading-4">
        {data.enseigne}
      </h1>

      {/* ── Positionnement prix ─────────────────────────────────────── */}
      <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
        <h2 className="text-lg font-bold text-dark dark:text-white">
          Positionnement prix
        </h2>
        {hasIndex ? (
          <>
            <div className="mt-4 flex items-baseline gap-3">
              <span className="text-heading-3 font-bold tabular-nums text-dark dark:text-white">
                {Math.round(index!)}
              </span>
              <DeltaPill pct={delta} />
            </div>
            <p className="mt-2 max-w-2xl text-sm text-dark-5 dark:text-dark-6">
              Sur {formatNumber(data.matched_products)} produits comparables,{" "}
              <span className="font-medium text-dark dark:text-white">
                {data.enseigne}
              </span>{" "}
              est globalement {positioning} que l&apos;ensemble des enseignes.
              {data.observations != null && (
                <>
                  {" "}
                  · {formatNumber(data.observations)} relevés sur{" "}
                  {data.window_weeks} semaines.
                </>
              )}
            </p>
            <p className="mt-2 text-xs text-dark-5 dark:text-dark-6">
              Indice 100 = niveau médian des enseignes · moins de 100 = moins
              chère · plus de 100 = plus chère.
            </p>
          </>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-stroke bg-gray-1 p-5 text-sm text-dark-5 dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6">
            Pas encore assez de produits comparés chez {data.enseigne} pour un
            indice fiable ({formatNumber(data.matched_products)} à ce jour). Les
            produits ci-dessous restent indicatifs.
          </div>
        )}
      </section>

      {/* ── Moins chère ─────────────────────────────────────────────── */}
      <section className="mt-6 rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
        <h2 className="text-lg font-bold text-dark dark:text-white">
          Là où {data.enseigne} est la moins chère
        </h2>
        <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
          Produits moins chers que la médiane des enseignes
        </p>
        <ProductRankList
          items={data.cheaper}
          emptyMessage={`${data.enseigne} n'est la moins chère sur aucun produit comparé sur la période.`}
        />
      </section>

      {/* ── Plus chère ──────────────────────────────────────────────── */}
      <section className="mt-6 rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
        <h2 className="text-lg font-bold text-dark dark:text-white">
          Là où {data.enseigne} est la plus chère
        </h2>
        <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
          Produits plus chers que la médiane des enseignes
        </p>
        <ProductRankList
          items={data.dearer}
          emptyMessage={`${data.enseigne} n'est la plus chère sur aucun produit comparé sur la période.`}
        />
      </section>
    </>
  );
}

// « X % moins chère » / « au niveau médian » / « X % plus chère ».
function qualifier(index: number): string {
  const delta = index - 100;
  if (Math.abs(delta) < 0.5) return "au niveau médian";
  if (delta < 0) return `${Math.round(Math.abs(delta))} % moins chère`;
  return `${Math.round(delta)} % plus chère`;
}

function BackLink() {
  return (
    <Link href="/enseignes" className="text-sm text-primary hover:underline">
      ← Enseignes
    </Link>
  );
}
