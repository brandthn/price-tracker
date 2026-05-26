import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api/client";
import { getProduct, getSubstitutes } from "@/lib/api/products";
import type { Product, Substitute } from "@/lib/api/types";

export const dynamic = "force-dynamic";

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

  // Substituts : best-effort (404 si pas d'embedding → on affiche juste vide).
  let substitutes: Substitute[] = [];
  try {
    substitutes = await getSubstitutes(ean, 5);
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) {
      // Erreur autre que 404 : on log côté serveur mais on n'échoue pas
      // la page. La détail produit reste prioritaire.
      console.error("[substitutes]", err);
    }
  }

  const offMissing = !product.off_found;

  return (
    <>
      <Link
        href="/products"
        className="text-sm text-primary hover:underline"
      >
        ← Catalogue
      </Link>

      <div className="mt-2 mb-6 flex flex-col gap-1">
        <h1 className="text-heading-4 font-bold text-dark dark:text-white">
          {product.name ?? <em>Produit sans nom</em>}
        </h1>
        <p className="text-sm text-dark-6">
          {product.brand && <span className="font-medium">{product.brand}</span>}
          {product.brand && <span className="mx-2 opacity-50">·</span>}
          <code className="text-xs">{product.ean}</code>
        </p>
      </div>

      {offMissing && (
        <div className="mb-6 rounded-lg border border-yellow-light bg-yellow-light/20 p-3 text-sm text-orange-light-1 dark:border-yellow-dark dark:bg-yellow-dark/20">
          ℹ️ Fiche produit en cours d&apos;enrichissement.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
          {product.image_url ? (
            <div className="relative aspect-square w-full overflow-hidden rounded bg-gray-2">
              {/* next/image distant : on n'ajoute pas le hostname OFF par défaut,
                  donc on utilise une balise <img> classique. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={product.image_url}
                alt={product.name ?? product.ean}
                className="size-full object-contain"
              />
            </div>
          ) : (
            <div className="grid aspect-square place-items-center rounded bg-gray-2 text-sm text-dark-6 dark:bg-dark-3">
              Pas d&apos;image
            </div>
          )}
        </div>

        <div className="lg:col-span-2 space-y-6">
          <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
            <h2 className="mb-4 text-heading-6 font-bold text-dark dark:text-white">
              Informations
            </h2>
            <dl className="grid grid-cols-1 gap-y-2 text-sm sm:grid-cols-2">
              <Field label="Rayon" value={product.category_l1} />
              <Field label="Sous-rayon" value={product.category_l2} />
              <Field label="Famille" value={product.category_l3} />
              <Field label="Nutri-Score" value={product.nutriscore?.toUpperCase()} />
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
                Stats marque « {product.brand} » →
              </Link>
            )}
          </div>

          <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
            <h2 className="mb-4 text-heading-6 font-bold text-dark dark:text-white">
              Produits similaires
            </h2>
            {substitutes.length === 0 ? (
              <p className="text-sm text-dark-6">
                Pas de produit similaire à proposer pour le moment.
              </p>
            ) : (
              <ul className="divide-y divide-stroke dark:divide-dark-3">
                {substitutes.map((s) => (
                  <li key={s.ean}>
                    <Link
                      href={`/products/${s.ean}`}
                      className="flex items-center justify-between gap-3 py-2.5 hover:bg-gray-1 dark:hover:bg-dark-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-dark dark:text-white">
                          {s.name ?? s.ean}
                        </div>
                        <div className="text-xs text-dark-6">
                          {s.brand ?? "—"}
                          {s.category_l3 && (
                            <span className="ml-2 opacity-70">
                              · {s.category_l3}
                            </span>
                          )}
                        </div>
                      </div>
                      <span className="shrink-0 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
                        {(s.similarity * 100).toFixed(0)}%
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-dark-6">{label} :</dt>
      <dd className="font-medium text-dark dark:text-white">
        {value ?? <span className="text-dark-6">—</span>}
      </dd>
    </div>
  );
}
