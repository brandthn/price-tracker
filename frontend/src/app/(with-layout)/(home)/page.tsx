import Link from "next/link";
import {
  getHallOfShame,
  getInflationMap,
  getNationalIndex,
  getRankings,
  type Granularity,
} from "@/lib/api/indices";
import type { InflationIndex } from "@/lib/api/types";
import { TrendChart } from "@/components/charts/trend-chart";
import { FranceMap } from "@/components/charts/france-map";
import { MoversList } from "@/components/charts/movers-list";
import { DeltaPill } from "@/components/ui/delta-pill";
import { GranularityToggle } from "@/components/ui/granularity-toggle";
import { formatDateLong, formatNumber } from "@/lib/format-fr";

export const dynamic = "force-dynamic";

// allSettled: une table Gold vide ou une erreur BQ ne doit pas tuer la page
export default async function ObservatoirePage({
  searchParams,
}: {
  searchParams: Promise<{ g?: string }>;
}) {
  const { g } = await searchParams;
  const gran: Granularity = g === "month" ? "month" : "week";
  const perStep = gran === "month" ? "d'un mois à l'autre" : "d'une semaine à l'autre";

  const [nationalR, mapR, upR, downR, shameR] = await Promise.allSettled([
    getNationalIndex(gran),
    getInflationMap(gran),
    getRankings(8, "up", gran),
    getRankings(8, "down", gran),
    getHallOfShame(5, gran),
  ]);

  const national = settled(nationalR);
  const map = settled(mapR);
  const up = settled(upR);
  const down = settled(downR);
  const shame = settled(shameR);

  const apiDown = !national && !map && !up && !down && !shame;

  return (
    <>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-heading-5 font-bold text-dark dark:text-white sm:text-heading-4">
            L&apos;inflation en France
          </h1>
          <p className="mt-1 max-w-xl text-sm text-dark-5 dark:text-dark-6">
            Suivi des prix à partir de relevés en magasin : indice d&apos;ensemble,
            évolutions par produit et lecture régionale.
          </p>
        </div>
        <Link
          href="/tickets/upload"
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90"
        >
          <span aria-hidden>+</span> Ajouter un ticket
        </Link>
      </div>

      <div className="mb-6 flex items-center gap-3">
        <GranularityToggle value={gran} />
        <span className="text-xs text-dark-5 dark:text-dark-6">
          Granularité de lecture
        </span>
      </div>

      {apiDown && (
        <div className="mb-6 rounded-2xl border border-red-light bg-red-light-6 p-5 text-sm text-red dark:border-red-dark dark:bg-red/10">
          L&apos;observatoire est momentanément indisponible. Réessayez dans
          quelques instants. Vos données ne sont pas perdues.
        </div>
      )}

      <NationalIndexCard index={national} granularity={gran} />

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark lg:col-span-2">
          <h2 className="text-lg font-bold text-dark dark:text-white">
            Et près de chez vous ?
          </h2>
          <p className="mb-4 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
            Variation des prix par département
            {map?.period && <> · relevés jusqu&apos;au {formatDateLong(map.period)}</>}
          </p>
          {map && map.values.length > 0 ? (
            <FranceMap values={map.values} />
          ) : (
            <EmptyBlock>
              La lecture départementale se construit : elle apparaîtra dès
              qu&apos;assez de relevés géolocalisés seront réunis.
            </EmptyBlock>
          )}
        </section>

        <div className="grid gap-6 sm:grid-cols-2 lg:col-span-3 lg:grid-cols-1 xl:grid-cols-2">
          <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
            <h2 className="text-lg font-bold text-dark dark:text-white">
              Ce qui monte
            </h2>
            <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
              Les plus fortes hausses {perStep}
            </p>
            <MoversList
              items={up?.items ?? []}
              emptyMessage="Pas de hausse marquante détectée sur la période, ou pas encore assez de relevés."
            />
          </section>

          <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
            <h2 className="text-lg font-bold text-dark dark:text-white">
              Ce qui baisse
            </h2>
            <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
              Les baisses à saisir {perStep}
            </p>
            <MoversList
              items={down?.items ?? []}
              emptyMessage="Pas de baisse marquante détectée sur la période, ou pas encore assez de relevés."
            />
          </section>
        </div>
      </div>

      {shame && shame.items.length > 0 && (
        <section className="mt-6 rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
          <h2 className="text-lg font-bold text-dark dark:text-white">
            Les hausses les plus visibles
          </h2>
          <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
            Produits très relevés et en forte hausse, ceux qui pèsent le plus en
            caisse
          </p>
          <MoversList items={shame.items} emptyMessage="" />
        </section>
      )}

      <section className="mt-6 rounded-2xl bg-primary/5 p-6 dark:bg-primary/10 sm:p-8">
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h2 className="text-lg font-bold text-dark dark:text-white">
              Et vos dépenses ?
            </h2>
            <p className="mt-1 max-w-lg text-sm text-dark-5 dark:text-dark-6">
              Ajoutez vos tickets de caisse : PriceTracker suit votre panier
              réel, vos produits habituels et vos dépenses mois par mois.
            </p>
          </div>
          <Link
            href="/budget"
            className="shrink-0 rounded-xl border border-primary px-5 py-2.5 text-sm font-semibold text-primary hover:bg-primary hover:text-white"
          >
            Voir mon budget →
          </Link>
        </div>
      </section>
    </>
  );
}

function NationalIndexCard({
  index,
  granularity,
}: {
  index: InflationIndex | null;
  granularity: Granularity;
}) {
  const hasSeries = !!index && index.series.length >= 2;
  const deltaPct =
    hasSeries && index.current != null ? index.current - 100 : null;
  const lastPoint = hasSeries ? index.series[index.series.length - 1] : null;
  const stepLabel = granularity === "month" ? "ce mois" : "cette semaine";

  return (
    <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="lg:w-64 lg:shrink-0">
          <h2 className="text-lg font-bold text-dark dark:text-white">
            Indice PriceTracker
          </h2>
          <p className="mt-0.5 text-xs text-dark-5 dark:text-dark-6">
            Évolution des prix en magasin, toutes enseignes confondues
          </p>

          {deltaPct != null ? (
            <>
              <div className="mt-5 flex items-baseline gap-3">
                <span className="text-heading-3 font-bold text-dark dark:text-white">
                  {index!.current!.toLocaleString("fr-FR", {
                    maximumFractionDigits: 1,
                  })}
                </span>
                <DeltaPill pct={deltaPct} />
              </div>
              <p className="mt-2 text-xs text-dark-5 dark:text-dark-6">
                Base 100{" "}
                {index!.base_period && (
                  <>le {formatDateLong(index!.base_period)}</>
                )}
                {lastPoint?.sample_size != null && (
                  <>
                    {" "}
                    · {formatNumber(lastPoint.sample_size)} relevés {stepLabel}
                  </>
                )}
              </p>
            </>
          ) : (
            <EmptyBlock className="mt-5">
              L&apos;indice se calcule dès que la fenêtre de relevés est
              suffisante. Les premiers chiffres arrivent, revenez bientôt.
            </EmptyBlock>
          )}
        </div>

        {hasSeries && (
          <div className="min-w-0 flex-1">
            <TrendChart
              points={index!.series.map((p) => ({
                date: p.date,
                value: p.value,
                sampleSize: p.sample_size,
              }))}
              unit="index"
              baseline={100}
              ariaLabel="Indice d'inflation PriceTracker (base 100)"
            />
          </div>
        )}
      </div>
    </section>
  );
}

function EmptyBlock({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-dashed border-stroke bg-gray-1 p-5 text-sm text-dark-5 dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6 ${className}`}
    >
      {children}
    </div>
  );
}

function settled<T>(r: PromiseSettledResult<T>): T | null {
  return r.status === "fulfilled" ? r.value : null;
}
