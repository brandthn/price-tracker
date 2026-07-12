import Link from "next/link";
import { notFound } from "next/navigation";
import { getTicket } from "@/lib/api/tickets";
import { ApiError } from "@/lib/api/client";
import { StatusBadge } from "@/components/ui/status-badge";
import { ItemsValidator } from "./_components/items-validator";
import { OcrFeedback } from "./_components/ocr-feedback";
import { TicketImage } from "./_components/ticket-image";

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

  const hasOcrResult =
    ticket.status === "ocr_done" || ticket.status === "validated";

  return (
    <>
      <div className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href="/tickets" className="text-sm text-primary hover:underline">
            ← Mes tickets
          </Link>
          <h1 className="mt-2 text-heading-4 font-bold text-dark dark:text-white">
            {ticket.enseigne ?? "Ticket sans enseigne"}
          </h1>
          <p className="text-sm text-dark-6">
            {ticket.date_ticket ?? "Date inconnue"}
          </p>
        </div>
        <StatusBadge status={ticket.status} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Colonne gauche : la photo du ticket, visible d'emblée. */}
        <aside className="space-y-4">
          <TicketImage ticketId={ticket.id} />
          <ReadingCard ticket={ticket} />
        </aside>

        {/* Colonne droite : lecture à vérifier, dépliée. */}
        <div className="space-y-6 lg:col-span-2">
          {hasOcrResult && (
            // key sur ocr_attempts : chaque passe OCR remonte le composant, qui
            // repart de props frais (feedback, baseline de poll) — sinon l'état
            // rémanent désynchronise les boutons et fausse le « maximum atteint ».
            <OcrFeedback
              key={ticket.ocr_attempts}
              ticketId={ticket.id}
              initialFeedback={ticket.last_feedback}
              initialAttempts={ticket.ocr_attempts}
            />
          )}

          <ItemsValidator
            key={ticket.ocr_attempts}
            ticketId={ticket.id}
            initialItems={ticket.items}
            ticketStatus={ticket.status}
          />
        </div>
      </div>
    </>
  );
}

function ReadingCard({
  ticket,
}: {
  ticket: Awaited<ReturnType<typeof getTicket>>;
}) {
  const hasAnalyse = ticket.ocr_confidence != null || ticket.ocr_error;
  if (!hasAnalyse) return null;

  return (
    <div className="rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark">
      <h3 className="mb-3 text-sm font-semibold uppercase text-dark-6">
        Lecture du ticket
      </h3>
      <dl className="space-y-2 text-sm">
        {ticket.ocr_confidence != null && (
          <Row
            label="Qualité de lecture"
            value={`${(ticket.ocr_confidence * 100).toFixed(0)} %`}
          />
        )}
        {ticket.ocr_error && (
          <Row
            label="Lecture"
            value="Échouée — reprenez la photo, bien à plat et nette."
            variant="error"
          />
        )}
      </dl>
    </div>
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
