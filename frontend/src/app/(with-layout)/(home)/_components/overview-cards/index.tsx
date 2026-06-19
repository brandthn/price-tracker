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
  const counters = countTickets(list.items);

  return (
    <div className="grid gap-4 sm:grid-cols-2 sm:gap-6 xl:grid-cols-4 2xl:gap-7.5">
      <OverviewCard
        label="Total tickets"
        value={total}
        hint="cumul utilisateur démo"
        Icon={icons.TotalTicketsIcon}
      />
      <OverviewCard
        label="En analyse"
        value={counters.analyzing}
        hint="OCR en cours"
        Icon={icons.PendingIcon}
      />
      <OverviewCard
        label="👍 Utiles"
        value={counters.up}
        hint="output OCR jugé correct"
        Icon={icons.ValidatedIcon}
      />
      <OverviewCard
        label="👎 À revoir"
        value={counters.down}
        hint="re-analysés (tier-2)"
        Icon={icons.OcrDoneIcon}
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

const ANALYZING_STATUSES = new Set([
  "pending",
  "processing",
  "ocr_processing",
]);

function countTickets(items: Ticket[]) {
  const c = { analyzing: 0, up: 0, down: 0 };
  for (const t of items) {
    if (ANALYZING_STATUSES.has(t.status)) c.analyzing += 1;
    if (t.last_feedback === "up") c.up += 1;
    else if (t.last_feedback === "down") c.down += 1;
  }
  return c;
}
