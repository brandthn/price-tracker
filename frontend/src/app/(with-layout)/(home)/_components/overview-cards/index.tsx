import { listTickets } from "@/lib/api/tickets";
import type { Ticket } from "@/lib/api/types";
import { OverviewCard } from "./card";
import * as icons from "./icons";

export async function OverviewCardsGroup() {
  // On rapatrie 100 tickets max pour compter par statut. Au-delà, le total
  // est juste affiché tel quel depuis l'API.
  const list = await listTickets(100, 0).catch(() => null);

  if (!list) {
    return (
      <OverviewCardsEmpty
        reason="Impossible de joindre l'API backend. Vérifie NEXT_PUBLIC_API_BASE_URL." />
    );
  }

  const total = list.total;
  const counters = countByStatus(list.items);

  return (
    <div className="grid gap-4 sm:grid-cols-2 sm:gap-6 xl:grid-cols-4 2xl:gap-7.5">
      <OverviewCard
        label="Total tickets"
        value={total}
        hint="cumul utilisateur démo"
        Icon={icons.TotalTicketsIcon}
      />
      <OverviewCard
        label="En attente OCR"
        value={counters.pending + counters.processing}
        hint="pending / processing"
        Icon={icons.PendingIcon}
      />
      <OverviewCard
        label="OCR terminé"
        value={counters.ocr_done}
        hint="lignes prêtes à valider"
        Icon={icons.OcrDoneIcon}
      />
      <OverviewCard
        label="Validés"
        value={counters.validated}
        hint="corrigés par l'utilisateur"
        Icon={icons.ValidatedIcon}
      />
    </div>
  );
}

function OverviewCardsEmpty({ reason }: { reason: string }) {
  return (
    <div className="rounded-[10px] border border-red-light bg-red-light-5 p-6 text-sm text-red shadow-1 dark:border-red-dark dark:bg-red/10">
      ⚠️ {reason}
    </div>
  );
}

function countByStatus(items: Ticket[]) {
  const c = {
    pending: 0,
    processing: 0,
    ocr_done: 0,
    ocr_failed: 0,
    validated: 0,
  };
  for (const t of items) {
    if (t.status in c) c[t.status as keyof typeof c] += 1;
  }
  return c;
}
