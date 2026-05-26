import Link from "next/link";
import { notFound } from "next/navigation";
import { getTicket } from "@/lib/api/tickets";
import { ApiError } from "@/lib/api/client";
import { StatusBadge } from "@/components/ui/status-badge";
import { ItemsValidator } from "./_components/items-validator";

export const dynamic = "force-dynamic";

export default async function TicketDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let ticket: Awaited<ReturnType<typeof getTicket>>;
  try {
    ticket = await getTicket(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  return (
    <>
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link
            href="/tickets"
            className="text-sm text-primary hover:underline"
          >
            ← Tickets
          </Link>
          <h1 className="mt-2 text-heading-4 font-bold text-dark dark:text-white">
            {ticket.enseigne ?? "Ticket sans enseigne"}
          </h1>
          <p className="text-sm text-dark-6">
            {ticket.date_ticket ?? "Date inconnue"} ·{" "}
            <code className="text-xs">{ticket.id}</code>
          </p>
        </div>
        <StatusBadge status={ticket.status} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Meta ticket={ticket} />

        <div className="lg:col-span-2">
          <ItemsValidator
            ticketId={ticket.id}
            initialItems={ticket.items}
            ticketStatus={ticket.status}
          />
        </div>
      </div>
    </>
  );
}

function Meta({
  ticket,
}: {
  ticket: Awaited<ReturnType<typeof getTicket>>;
}) {
  const hasAnalyse = ticket.ocr_confidence != null || ticket.ocr_error;
  return (
    <aside className="space-y-4">
      {hasAnalyse && (
        <div className="rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark">
          <h3 className="mb-3 text-sm font-semibold uppercase text-dark-6">
            Analyse
          </h3>
          <dl className="space-y-2 text-sm">
            {ticket.ocr_confidence != null && (
              <Row
                label="Confiance"
                value={`${(ticket.ocr_confidence * 100).toFixed(0)}%`}
              />
            )}
            {ticket.ocr_error && (
              <Row label="Erreur" value={ticket.ocr_error} variant="error" />
            )}
          </dl>
        </div>
      )}

      <div className="rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark">
        <h3 className="mb-3 text-sm font-semibold uppercase text-dark-6">
          Synthèse
        </h3>
        <dl className="space-y-2 text-sm">
          <Row
            label="Total ticket"
            value={
              ticket.total_eur != null
                ? `${ticket.total_eur.toFixed(2)} €`
                : "—"
            }
          />
          <Row label="Lignes" value={String(ticket.items.length)} />
          <Row
            label="Validées"
            value={String(ticket.items.filter((i) => i.validated_by_user).length)}
          />
        </dl>
      </div>
    </aside>
  );
}

function Row({
  label,
  value,
  variant = "default",
}: {
  label: string;
  value: string;
  variant?: "default" | "error";
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-dark-6">{label}</dt>
      <dd
        className={
          variant === "error"
            ? "text-right text-red"
            : "text-right font-medium text-dark dark:text-white"
        }
      >
        {value}
      </dd>
    </div>
  );
}
