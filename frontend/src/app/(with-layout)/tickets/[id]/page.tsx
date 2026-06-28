import Link from "next/link";
import { notFound } from "next/navigation";
import { getTicket } from "@/lib/api/tickets";
import { ApiError } from "@/lib/api/client";
import { StatusBadge } from "@/components/ui/status-badge";
import { ItemsValidator } from "./_components/items-validator";
import { OcrFeedback } from "./_components/ocr-feedback";

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

  // Le ticket est "pris en compte" dès l'OCR : on présente alors le feedback
  // 👍/👎, l'édition ligne-par-ligne devenant optionnelle.
  const hasOcrResult =
    ticket.status === "ocr_done" || ticket.status === "validated";

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

        <div className="space-y-6 lg:col-span-2">
          {hasOcrResult && (
            <OcrFeedback
              ticketId={ticket.id}
              initialFeedback={ticket.last_feedback}
              initialAttempts={ticket.ocr_attempts}
            />
          )}

          {hasOcrResult ? (
            <details className="group rounded-[10px] bg-white shadow-1 dark:bg-gray-dark">
              <summary className="cursor-pointer list-none px-5 py-4 text-sm font-medium text-dark-6 hover:text-dark dark:hover:text-white">
                ✏️ Corriger les lignes (optionnel)
                <span className="ml-1 text-xs text-dark-6 group-open:hidden">
                  — déplier
                </span>
              </summary>
              <div className="border-t border-stroke px-1 pb-1 dark:border-dark-3">
                <ItemsValidator
                  key={ticket.updated_at}
                  ticketId={ticket.id}
                  initialItems={ticket.items}
                  ticketStatus={ticket.status}
                />
              </div>
            </details>
          ) : (
            <ItemsValidator
              key={ticket.updated_at}
              ticketId={ticket.id}
              initialItems={ticket.items}
              ticketStatus={ticket.status}
            />
          )}
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
