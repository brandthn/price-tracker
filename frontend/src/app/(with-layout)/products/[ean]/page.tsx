import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api/client";
import {
  getProduct,
  getProductPrices,
  getSubstitutes,
} from "@/lib/api/products";
import type { Product, ProductPrices, Substitute } from "@/lib/api/types";
import { TrendChart } from "@/components/charts/trend-chart";
import { DeltaPill } from "@/components/ui/delta-pill";
import { formatDateLong, formatEuro } from "@/lib/format-fr";

export const dynamic = "force-dynamic";

// chaque source dégrade indépendamment (pas de relevés -> on garde la fiche, etc)
export default async function ProductDetailPage({
  params,
}: {
  params: Promise<{ ean: string }>;
}) {
  const { ean } = await params;

  let product: Product;
  try {
    product = await getProduct(ean);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const [pricesR, subsR] = await Promise.allSettled([
    getProductPrices(ean),
    getSubstitutes(ean, 5),
  ]);
  const prices: ProductPrices | null =
    pricesR.status === "fulfilled" ? pricesR.value : null;
  const substitutes: Substitute[] =
    subsR.status === "fulfilled" ? subsR.value : [];

  // 2 cas distincts: hors catalogue vs au catalogue mais enrichissement OFF pas fini
  const priceOnly = !product.catalog;
  const offMissing = product.catalog && !product.off_found;
  const hasSeries = !!prices && prices.series.length >= 2;
  const bestStore = prices?.by_store[0] ?? null;

  return (
    <>
      <Link href="/products" className="text-sm text-primary hover:underline">
        ← Produits &amp; prix
      </Link>

      <div className="mb-6 mt-2 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-heading-5 font-bold text-dark dark:text-white sm:text-heading-4">
            {product.name ?? (
              <em>{priceOnly ? "Produit non référencé" : "Produit sans nom"}</em>
            )}
          </h1>
          <p className="mt-1 text-sm text-dark-5 dark:text-dark-6">
            {product.brand && (
              <span className="font-medium text-dark dark:text-white">
                {product.brand}
              </span>
            )}
            {product.brand && <span className="mx-2 opacity-50">·</span>}
            <code className="text-xs">{product.ean}</code>
          </p>
        </div>

        {prices?.latest_median_eur != null && (
          <div className="flex items-baseline gap-3">
            <span className="text-heading-5 font-bold text-dark dark:text-white">
              {formatEuro(prices.latest_median_eur)}
            </span>
            {prices.pct_change_window != null && (
              <DeltaPill pct={prices.pct_change_window} />
            )}
          </div>
        )}
      </div>

      {priceOnly && (
        <div className="mb-6 rounded-xl border border-dashed border-stroke bg-gray-1 p-4 text-sm text-dark-5 dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6">
          Ce produit n&apos;est pas encore au catalogue : il est suivi
          uniquement par ses relevés de prix ci-dessous.
        </div>
      )}

      {offMissing && (
        <div className="mb-6 rounded-xl border border-dashed border-stroke bg-gray-1 p-4 text-sm text-dark-5 dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6">
          La fiche de ce produit est en cours d&apos;enrichissement — les
          prix restent suivis normalement.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6">
          <div className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
            {product.image_url ? (
              <div className="relative aspect-square w-full overflow-hidden rounded-xl bg-gray-1 dark:bg-dark-2">
                {/* hostname OFF pas déclaré dans next.config */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={product.image_url}
                  alt={product.name ?? product.ean}
                  className="size-full object-contain"
                />
              </div>
            ) : (
              <div className="grid aspect-square place-items-center rounded-xl bg-gray-1 text-sm text-dark-5 dark:bg-dark-2 dark:text-dark-6">
                Pas d&apos;image
              </div>
            )}
          </div>

          <div
            className={`rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark ${
              priceOnly ? "hidden" : ""
            }`}
          >
            <h2 className="mb-4 text-lg font-bold text-dark dark:text-white">
              Identité
            </h2>
            <dl className="space-y-2 text-sm">
              <Field label="Rayon" value={product.category_l1} />
              <Field label="Sous-rayon" value={product.category_l2} />
              <Field label="Famille" value={product.category_l3} />
              <Field
                label="Nutri-Score"
                value={product.nutriscore?.toUpperCase()}
              />
              <Field
                label="NOVA"
                value={product.nova != null ? String(product.nova) : null}
              />
              <Field label="Éco-Score" value={product.ecoscore?.toUpperCase()} />
            </dl>
            {product.brand && (
              <Link
                href={`/brands/${encodeURIComponent(product.brand)}`}
                className="mt-4 inline-block text-sm text-primary hover:underline"
              >
                Tous les produits {product.brand} →
              </Link>
            )}
          </div>
        </div>

        <div className="space-y-6 lg:col-span-2">
          <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
            <h2 className="text-lg font-bold text-dark dark:text-white">
              Le prix évolue comment ?
            </h2>
            <p className="mb-3 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
              Prix médian hebdomadaire, tous magasins confondus (relevés
              publics Open Prices)
            </p>
            {hasSeries ? (
              <TrendChart
                points={prices!.series.map((p) => ({
                  date: p.week,
                  value: p.median_price_eur,
                  sampleSize: p.observations,
                }))}
                unit="eur"
                ariaLabel={`Évolution du prix de ${product.name ?? product.ean}`}
              />
            ) : (
              <div className="rounded-xl border border-dashed border-stroke bg-gray-1 p-5 text-sm text-dark-5 dark:border-dark-3 dark:bg-dark-2 dark:text-dark-6">
                Pas encore de relevés de prix publics pour ce produit.
                Photographiez un ticket qui le contient : vous contribuerez à
                son suivi.
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
            <h2 className="text-lg font-bold text-dark dark:text-white">
              Où l&apos;acheter au meilleur prix ?
            </h2>
            <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
              Prix médians des 8 dernières semaines, par enseigne
            </p>
            {prices && prices.by_store.length > 0 ? (
              <ul className="divide-y divide-stroke dark:divide-dark-3">
                {prices.by_store.map((s, i) => (
                  <li
                    key={s.enseigne}
                    className="flex items-center gap-3 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium capitalize text-dark dark:text-white">
                          {s.enseigne}
                        </span>
                        {i === 0 && prices.by_store.length > 1 && (
                          <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                            Meilleur prix
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-dark-5 dark:text-dark-6">
                        {s.observations} relevé{s.observations > 1 ? "s" : ""}
                        {s.last_seen_week && (
                          <> · vu le {formatDateLong(s.last_seen_week)}</>
                        )}
                      </div>
                    </div>
                    <span
                      className="text-sm font-semibold text-dark dark:text-white"
                      style={{ fontVariantNumeric: "tabular-nums" }}
                    >
                      {formatEuro(s.median_price_eur)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-4 text-sm text-dark-5 dark:text-dark-6">
                Aucune enseigne n&apos;a encore de relevé récent pour ce
                produit.
              </p>
            )}
            {bestStore && prices!.by_store.length > 1 && (
              <p className="mt-2 text-xs text-dark-5 dark:text-dark-6">
                Écart max observé :{" "}
                {formatEuro(
                  prices!.by_store[prices!.by_store.length - 1]
                    .median_price_eur - bestStore.median_price_eur,
                )}{" "}
                sur le même produit.
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
            <h2 className="text-lg font-bold text-dark dark:text-white">
              Produits proches
            </h2>
            <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
              Même famille, composition similaire — des pistes pour comparer
              ou remplacer
            </p>
            {substitutes.length === 0 ? (
              <p className="py-4 text-sm text-dark-5 dark:text-dark-6">
                Pas d&apos;alternative à proposer pour le moment.
              </p>
            ) : (
              <ul className="divide-y divide-stroke dark:divide-dark-3">
                {substitutes.map((s) => (
                  <li key={s.ean}>
                    <Link
                      href={`/products/${s.ean}`}
                      className="flex items-center justify-between gap-3 rounded-lg px-1 py-2.5 hover:bg-gray-1 dark:hover:bg-dark-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-dark dark:text-white">
                          {s.name ?? s.ean}
                        </div>
                        <div className="text-xs text-dark-5 dark:text-dark-6">
                          {s.brand ?? "—"}
                          {s.nutriscore && (
                            <span className="ml-2 opacity-70">
                              Nutri-Score {s.nutriscore.toUpperCase()}
                            </span>
                          )}
                        </div>
                      </div>
                      <span className="shrink-0 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                        {(s.similarity * 100).toFixed(0)} % proche
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-dark-5 dark:text-dark-6">{label}</dt>
      <dd className="text-right font-medium text-dark dark:text-white">
        {value ?? <span className="text-dark-5 dark:text-dark-6">—</span>}
      </dd>
    </div>
  );
}
