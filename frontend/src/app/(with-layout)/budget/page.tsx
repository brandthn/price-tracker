import Link from "next/link";
import { getMyBasket, getMyRecommendations } from "@/lib/api/users";
import type { BasketSummary, RecommendationsOut } from "@/lib/api/types";
import { MonthlyBars } from "@/components/charts/monthly-bars";
import { StatTile } from "@/components/ui/stat-tile";
import { DeltaPill } from "@/components/ui/delta-pill";
import { formatDateLong, formatEuro } from "@/lib/format-fr";

export const dynamic = "force-dynamic";

// tout vient des tickets de l'user, rien de simulé
export default async function BudgetPage() {
  let basket: BasketSummary | null = null;
  let recommendations: RecommendationsOut | null = null;
  let error: string | null = null;
  try {
    basket = await getMyBasket();
  } catch (err) {
    error = (err as Error).message;
  }

  // optionnel, une erreur ici ne doit pas casser la page
  if (basket && basket.tickets_count > 0) {
    try {
      recommendations = await getMyRecommendations();
    } catch {
      recommendations = null;
    }
  }


  const hasData = !!basket && basket.tickets_count > 0;
  const monthly = basket?.monthly ?? [];
  const lastMonth = monthly.at(-1) ?? null;
  const prevMonth = monthly.at(-2) ?? null;
  const monthDeltaPct =
    lastMonth && prevMonth && prevMonth.total_eur > 0
      ? ((lastMonth.total_eur - prevMonth.total_eur) / prevMonth.total_eur) *
        100
      : null;

  return (
    <>
      <div className="mb-7">
        <h1 className="text-heading-5 font-bold text-dark dark:text-white sm:text-heading-4">
          Mon budget
        </h1>
        <p className="mt-1 max-w-xl text-sm text-dark-5 dark:text-dark-6">
          Votre panier réel, reconstruit à partir de vos tickets de caisse.
        </p>
      </div>

      {error && (
        <div className="mb-6 rounded-2xl border border-red-light bg-red-light-6 p-5 text-sm text-red dark:border-red-dark dark:bg-red/10">
          Impossible de charger votre budget pour le moment. Réessayez dans
          quelques instants.
        </div>
      )}

      {!error && !hasData && <Onboarding />}

      {hasData && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Dépenses ce mois-ci"
              value={
                lastMonth ? formatEuro(lastMonth.total_eur) : "—"
              }
              context={
                monthDeltaPct != null && (
                  <>
                    <DeltaPill pct={monthDeltaPct} />
                    <span>vs mois précédent</span>
                  </>
                )
              }
            />
            <StatTile
              label="Panier moyen"
              value={
                basket!.avg_ticket_eur != null
                  ? formatEuro(basket!.avg_ticket_eur)
                  : "—"
              }
              context={<span>par passage en caisse</span>}
            />
            <StatTile
              label="Tickets suivis"
              value={basket!.tickets_count}
              context={
                basket!.first_ticket_date && (
                  <span>
                    depuis le {formatDateLong(basket!.first_ticket_date)}
                  </span>
                )
              }
            />
            <StatTile
              label="Total suivi"
              value={
                basket!.total_spent_eur != null
                  ? formatEuro(basket!.total_spent_eur)
                  : "—"
              }
              context={<span>cumul de vos tickets</span>}
            />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-5">
            <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark lg:col-span-3">
              <h2 className="text-lg font-bold text-dark dark:text-white">
                Vos dépenses, mois par mois
              </h2>
              <p className="mb-3 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
                Somme des tickets dont le total a pu être lu
              </p>
              {monthly.length > 0 ? (
                <MonthlyBars months={monthly} />
              ) : (
                <p className="py-6 text-sm text-dark-5 dark:text-dark-6">
                  Vos prochains tickets alimenteront ce graphique.
                </p>
              )}
            </section>

            <section className="rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark lg:col-span-2">
              <h2 className="text-lg font-bold text-dark dark:text-white">
                Vos produits habituels
              </h2>
              <p className="mb-2 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
                Les articles qui reviennent le plus dans vos tickets
              </p>
              {basket!.top_products.length === 0 ? (
                <p className="py-4 text-sm text-dark-5 dark:text-dark-6">
                  Encore un peu de patience : vos habitudes apparaîtront après
                  quelques tickets.
                </p>
              ) : (
                <ul className="divide-y divide-stroke dark:divide-dark-3">
                  {basket!.top_products.map((p) => {
                    const inner = (
                      <div className="flex items-center gap-3 py-3">
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-dark dark:text-white">
                            {p.label}
                          </div>
                          <div className="text-xs text-dark-5 dark:text-dark-6">
                            acheté {p.purchases} fois
                            {p.last_purchased && (
                              <> · dernier achat {formatDateLong(p.last_purchased)}</>
                            )}
                          </div>
                        </div>
                        {p.avg_price_eur != null && (
                          <span
                            className="shrink-0 text-sm font-semibold text-dark dark:text-white"
                            style={{ fontVariantNumeric: "tabular-nums" }}
                          >
                            {formatEuro(p.avg_price_eur)}
                          </span>
                        )}
                      </div>
                    );
                    return (
                      <li key={`${p.ean ?? p.label}`}>
                        {p.ean ? (
                          <Link
                            href={`/products/${p.ean}`}
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
              )}
            </section>
          </div>

          <section className="mt-6 rounded-2xl bg-primary/5 p-6 dark:bg-primary/10">
            <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
              <p className="max-w-lg text-sm text-dark-5 dark:text-dark-6">
                Plus vous ajoutez de tickets, plus votre suivi est fidèle — et
                plus l&apos;observatoire est précis pour tout le monde.
              </p>
              <Link
                href="/tickets/upload"
                className="shrink-0 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:opacity-90"
              >
                + Ajouter un ticket
              </Link>
            </div>
          </section>
          {recommendations && recommendations.items.length > 0 && (
            <section className="mt-6 rounded-2xl border border-stroke bg-white p-6 dark:border-dark-3 dark:bg-gray-dark">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-bold text-dark dark:text-white">
                  Économies possibles
                </h2>
                <span className="text-sm font-semibold text-green dark:text-green">
                  jusqu&apos;à {formatEuro(recommendations.total_monthly_saving_eur)} / mois
                </span>
              </div>
              <p className="mb-3 mt-0.5 text-xs text-dark-5 dark:text-dark-6">
                Des équivalents moins chers pour des produits que vous achetez déjà
              </p>

              <ul className="divide-y divide-stroke dark:divide-dark-3">
                {recommendations.items.map((item) => (
                  <li key={`${item.source.ean}-${item.target.ean}`} className="py-3">
                    <div className="flex items-center gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 text-sm">
                          <span className="truncate text-dark-5 line-through dark:text-dark-6">
                            {item.source.name ?? item.source.ean}
                          </span>
                          <span aria-hidden className="text-dark-5 dark:text-dark-6">
                            →
                          </span>
                          <Link
                            href={`/products/${item.target.ean}`}
                            className="truncate font-medium text-dark hover:underline dark:text-white"
                          >
                            {item.target.name ?? item.target.ean}
                          </Link>
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-xs text-dark-5 dark:text-dark-6">
                          <DeltaPill pct={-item.saving_pct} />
                          <span>
                            {formatEuro(item.source.price_per_unit)} → {formatEuro(item.target.price_per_unit)} / {item.unit}
                          </span>
                        </div>
                      </div>
                      <span
                        className="shrink-0 text-sm font-semibold text-green"
                        style={{ fontVariantNumeric: "tabular-nums" }}
                      >
                        −{formatEuro(item.monthly_saving_eur)}/mois
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </>
  );
}

function Onboarding() {
  return (
    <div className="rounded-2xl border border-stroke bg-white p-8 text-center dark:border-dark-3 dark:bg-gray-dark sm:p-12">
      <div
        aria-hidden
        className="mx-auto grid size-14 place-items-center rounded-2xl bg-primary/10 text-2xl"
      >
        🧾
      </div>
      <h2 className="mt-4 text-lg font-bold text-dark dark:text-white">
        Votre budget commence par un ticket
      </h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-dark-5 dark:text-dark-6">
        Photographiez un ticket de caisse : PriceTracker lit les articles et
        les prix, puis reconstruit vos dépenses et vos produits habituels.
        Deux minutes, et votre suivi démarre.
      </p>
      <Link
        href="/tickets/upload"
        className="mt-6 inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-white hover:opacity-90"
      >
        <span aria-hidden>+</span> Ajouter mon premier ticket
      </Link>
      <p className="mt-4 text-xs text-dark-5 dark:text-dark-6">
        Vos tickets restent privés. Seuls les prix anonymisés enrichissent
        l&apos;observatoire.
      </p>
    </div>
  );
}
