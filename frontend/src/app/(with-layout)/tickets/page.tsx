import Link from "next/link";
import { listTickets } from "@/lib/api/tickets";
import { StatusBadge } from "@/components/ui/status-badge";

export const dynamic = "force-dynamic";

export default async function TicketsPage({
  searchParams,
}: {
  searchParams: Promise<{ offset?: string }>;
}) {
  const { offset: rawOffset } = await searchParams;
  const offset = Number.parseInt(rawOffset ?? "0", 10) || 0;
  const limit = 20;

  let payload: Awaited<ReturnType<typeof listTickets>> | null = null;
  let error: string | null = null;
  try {
    payload = await listTickets(limit, offset);
  } catch (err) {
    error = (err as Error).message;
  }

  return (
    <>
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-heading-4 font-bold text-dark dark:text-white">
            Mes tickets
          </h1>
        </div>
        <Link
          href="/tickets/upload"
          className="inline-flex items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white hover:opacity-90"
        >
          + Uploader
        </Link>
      </div>

      {error && (
        <div className="mb-6 rounded-[10px] border border-red-light bg-red-light-5 p-4 text-sm text-red dark:border-red-dark dark:bg-red/10">
          ⚠️ {error}
        </div>
      )}

      {payload && (
        <div className="rounded-[10px] bg-white shadow-1 dark:bg-gray-dark">
          {payload.items.length === 0 ? (
            <div className="p-10 text-center">
              <p className="text-sm text-dark-6">
                Aucun ticket. Commence par{" "}
                <Link
                  href="/tickets/upload"
                  className="text-primary hover:underline"
                >
                  uploader le premier
                </Link>
                .
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-stroke text-left text-xs uppercase text-dark-6 dark:border-dark-3">
                <tr>
                  <th className="px-6 py-4 font-medium">Enseigne</th>
                  <th className="px-6 py-4 font-medium">Date</th>
                  <th className="px-6 py-4 font-medium text-right">Total</th>
                  <th className="px-6 py-4 font-medium">Statut</th>
                  <th className="px-6 py-4" />
                </tr>
              </thead>
              <tbody className="divide-y divide-stroke dark:divide-dark-3">
                {payload.items.map((t) => (
                  <tr
                    key={t.id}
                    className="hover:bg-gray-1 dark:hover:bg-dark-3"
                  >
                    <td className="px-6 py-4 font-medium text-dark dark:text-white">
                      {t.enseigne ?? (
                        <span className="text-dark-6">Inconnue</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-dark-6">
                      {t.date_ticket ?? "—"}
                    </td>
                    <td className="px-6 py-4 text-right font-medium text-dark dark:text-white">
                      {t.total_eur != null ? `${t.total_eur.toFixed(2)} €` : "—"}
                    </td>
                    <td className="px-6 py-4">
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="px-6 py-4 text-right">
                      <Link
                        href={`/tickets/${t.id}`}
                        className="text-primary hover:underline"
                      >
                        Détails →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Pagination */}
          <Pagination
            limit={limit}
            offset={offset}
            total={payload.total}
          />
        </div>
      )}
    </>
  );
}

function Pagination({
  limit,
  offset,
  total,
}: {
  limit: number;
  offset: number;
  total: number;
}) {
  if (total <= limit) return null;
  const prevOffset = Math.max(0, offset - limit);
  const nextOffset = offset + limit;
  const lastPage = nextOffset >= total;

  return (
    <div className="flex items-center justify-between border-t border-stroke px-6 py-3 text-sm dark:border-dark-3">
      <span className="text-dark-6">
        {offset + 1}–{Math.min(offset + limit, total)} sur {total}
      </span>
      <div className="flex gap-2">
        <PageLink
          href={`/tickets?offset=${prevOffset}`}
          disabled={offset === 0}
        >
          ← Précédent
        </PageLink>
        <PageLink
          href={`/tickets?offset=${nextOffset}`}
          disabled={lastPage}
        >
          Suivant →
        </PageLink>
      </div>
    </div>
  );
}

function PageLink({
  href,
  disabled,
  children,
}: {
  href: string;
  disabled: boolean;
  children: React.ReactNode;
}) {
  if (disabled) {
    return (
      <span className="cursor-not-allowed rounded border border-stroke px-3 py-1.5 text-dark-5 dark:border-dark-3">
        {children}
      </span>
    );
  }
  return (
    <Link
      href={href}
      className="rounded border border-stroke px-3 py-1.5 text-dark hover:bg-gray-1 dark:border-dark-3 dark:text-white dark:hover:bg-dark-3"
    >
      {children}
    </Link>
  );
}
