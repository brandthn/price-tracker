import Link from "next/link";
import { searchProducts } from "@/lib/api/products";
import { SearchBox } from "./_components/search-box";

export const dynamic = "force-dynamic";

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const query = q?.trim() ?? "";

  let result: Awaited<ReturnType<typeof searchProducts>> | null = null;
  let error: string | null = null;
  if (query.length >= 2) {
    try {
      result = await searchProducts(query, 30);
    } catch (err) {
      error = (err as Error).message;
    }
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-heading-4 font-bold text-dark dark:text-white">
          Catalogue produits
        </h1>
      </div>

      <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
        <SearchBox initialValue={query} />

        {!query && (
          <p className="mt-6 text-sm text-dark-6">
            Tape au moins 2 caractères pour lancer une recherche (ex:{" "}
            <Link href="/products?q=coca" className="text-primary hover:underline">
              coca
            </Link>
            ,{" "}
            <Link href="/products?q=lidl" className="text-primary hover:underline">
              lidl
            </Link>
            ,{" "}
            <Link href="/products?q=lait" className="text-primary hover:underline">
              lait
            </Link>
            ).
          </p>
        )}

        {error && (
          <div className="mt-6 rounded-lg border border-red-light bg-red-light-5 p-3 text-sm text-red dark:border-red-dark dark:bg-red/10">
            ⚠️ {error}
          </div>
        )}

        {result && (
          <div className="mt-6">
            <p className="mb-3 text-xs uppercase text-dark-6">
              {result.total} résultat(s) pour &laquo; {query} &raquo;
            </p>

            {result.items.length === 0 ? (
              <p className="text-sm text-dark-6">
                Aucun produit ne correspond à ta recherche.
              </p>
            ) : (
              <ul className="divide-y divide-stroke dark:divide-dark-3">
                {result.items.map((p) => (
                  <li key={p.ean}>
                    <Link
                      href={`/products/${p.ean}`}
                      className="flex items-start justify-between gap-4 py-3 hover:bg-gray-1 dark:hover:bg-dark-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium text-dark dark:text-white">
                          {p.name ?? <em>(sans nom)</em>}
                        </div>
                        <div className="text-xs text-dark-6">
                          {p.brand ?? "—"}
                          {p.category_l3 && (
                            <span className="ml-2 opacity-70">· {p.category_l3}</span>
                          )}
                          <span className="ml-2 font-mono opacity-70">{p.ean}</span>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5 text-xs">
                        {p.nutriscore && (
                          <NutriBadge score={p.nutriscore} />
                        )}
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function NutriBadge({ score }: { score: string }) {
  const colors: Record<string, string> = {
    a: "bg-green text-white",
    b: "bg-green-light-2 text-white",
    c: "bg-yellow-light text-orange-light-1",
    d: "bg-orange-light text-white",
    e: "bg-red text-white",
  };
  const cls = colors[score.toLowerCase()] ?? "bg-gray-2 text-dark";
  return (
    <span
      className={`inline-grid size-6 place-items-center rounded-full text-xs font-bold uppercase ${cls}`}
    >
      {score}
    </span>
  );
}
