import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api/client";
import { getBrandStats } from "@/lib/api/stats";

export const dynamic = "force-dynamic";

export default async function BrandStatsPage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = await params;
  const brand = decodeURIComponent(name);

  let stats;
  try {
    stats = await getBrandStats(brand);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  return (
    <>
      <Link href="/products" className="text-sm text-primary hover:underline">
        ← Catalogue
      </Link>

      <div className="mt-2 mb-6">
        <h1 className="text-heading-4 font-bold text-dark dark:text-white">
          {stats.brand}
        </h1>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Produits référencés" value={String(stats.product_count)} />
        <Stat
          label="Prix moyen"
          value={
            stats.avg_price_eur != null
              ? `${stats.avg_price_eur.toFixed(2)} €`
              : "—"
          }
        />
        {stats.median_pct_change != null && (
          <Stat
            label="Variation médiane"
            value={`${stats.median_pct_change.toFixed(2)} %`}
          />
        )}
      </div>

      {stats.top_increases.length > 0 && (
        <div className="mt-6 rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
          <h2 className="mb-4 text-heading-6 font-bold text-dark dark:text-white">
            Top hausses
          </h2>
          <ul className="divide-y divide-stroke dark:divide-dark-3">
            {stats.top_increases.map((item) => (
              <li
                key={item.ean ?? item.produit_nom}
                className="flex items-center justify-between py-3"
              >
                <div>
                  <div className="text-sm font-medium text-dark dark:text-white">
                    {item.produit_nom ?? item.ean ?? "—"}
                  </div>
                  <div className="text-xs text-dark-6">
                    {item.price_eur_previous != null &&
                    item.price_eur_current != null
                      ? `${item.price_eur_previous.toFixed(2)} → ${item.price_eur_current.toFixed(2)} €`
                      : "—"}
                  </div>
                </div>
                <span className="rounded-full bg-red/10 px-2.5 py-0.5 text-sm font-medium text-red">
                  +{item.pct_change.toFixed(1)} %
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark">
      <div className="text-xs uppercase text-dark-6">{label}</div>
      <div className="mt-1 text-heading-5 font-bold text-dark dark:text-white">
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-dark-6">{hint}</div>}
    </div>
  );
}
