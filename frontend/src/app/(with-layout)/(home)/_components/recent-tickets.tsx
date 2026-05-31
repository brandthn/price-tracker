import { listTickets } from "@/lib/api/tickets";
import { StatusBadge } from "@/components/ui/status-badge";
import Link from "next/link";

export async function RecentTickets() {
  const list = await listTickets(5, 0).catch(() => null);

  if (!list) {
    return (
      <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
        <p className="text-sm text-dark-6">
          Backend injoignable — impossible de lister les tickets.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-[10px] bg-white p-6 shadow-1 dark:bg-gray-dark">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-heading-6 font-bold text-dark dark:text-white">
          Tickets récents
        </h2>
        <Link
          href="/tickets"
          className="text-sm font-medium text-primary hover:underline"
        >
          Voir tout →
        </Link>
      </div>

      {list.items.length === 0 ? (
        <div className="py-8 text-center text-sm text-dark-6">
          Pas encore de tickets.{" "}
          <Link href="/tickets/upload" className="text-primary hover:underline">
            Uploader un ticket
          </Link>
          .
        </div>
      ) : (
        <ul className="divide-y divide-stroke dark:divide-dark-3">
          {list.items.map((t) => (
            <li key={t.id}>
              <Link
                href={`/tickets/${t.id}`}
                className="flex items-center justify-between gap-4 py-3 hover:bg-gray-1 dark:hover:bg-dark-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-dark dark:text-white">
                    {t.enseigne ?? "Enseigne inconnue"}
                    {t.total_eur != null && (
                      <span className="ml-2 text-dark-6">
                        — {t.total_eur.toFixed(2)} €
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-dark-6">
                    {t.date_ticket ?? formatDate(t.created_at)}{" "}
                    <span className="opacity-60">· id {t.id.slice(0, 8)}</span>
                  </div>
                </div>
                <StatusBadge status={t.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
