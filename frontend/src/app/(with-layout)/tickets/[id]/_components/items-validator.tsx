"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { patchTicketItems } from "@/lib/api/tickets";
import type { PrixExtrait } from "@/lib/api/types";

const TICKET_VALIDATED = "validated";

type Draft = {
  id: string;
  ean: string;
  produit_nom: string;
  quantity: string;
  price_eur: string;
  dirty: boolean;
};

export function ItemsValidator({
  ticketId,
  initialItems,
  ticketStatus,
}: {
  ticketId: string;
  initialItems: PrixExtrait[];
  ticketStatus: string;
}) {
  const router = useRouter();
  const [drafts, setDrafts] = useState<Draft[]>(() =>
    initialItems.map(toDraft),
  );
  const [isPending, startTransition] = useTransition();

  const dirtyCount = useMemo(
    () => drafts.filter((d) => d.dirty).length,
    [drafts],
  );

  const isEmpty = initialItems.length === 0;
  const isAwaitingOcr =
    ticketStatus === "pending" || ticketStatus === "processing";
  const isValidated = ticketStatus === TICKET_VALIDATED;

  const update = (id: string, patch: Partial<Draft>) => {
    setDrafts((prev) =>
      prev.map((d) =>
        d.id === id ? { ...d, ...patch, dirty: true } : d,
      ),
    );
  };

  const submit = () => {
    const changed = drafts.filter((d) => d.dirty);

    startTransition(async () => {
      try {
        await patchTicketItems(
          ticketId,
          changed.map((d) => ({
            id: d.id,
            ean: emptyToNull(d.ean),
            produit_nom: emptyToNull(d.produit_nom),
            quantity: parseNumberOrNull(d.quantity),
            price_eur: parseNumberOrNull(d.price_eur),
          })),
        );
        toast.success(
          changed.length === 0
            ? "Ticket confirmé."
            : `Ticket confirmé (${changed.length} correction${changed.length > 1 ? "s" : ""}).`,
        );
        router.refresh();
      } catch (err) {
        toast.error(`Impossible de confirmer : ${(err as Error).message}`);
      }
    });
  };

  if (isEmpty) {
    return (
      <div className="rounded-[10px] bg-white p-6 text-sm shadow-1 dark:bg-gray-dark">
        <h3 className="mb-2 text-heading-6 font-bold text-dark dark:text-white">
          Articles du ticket
        </h3>
        {isAwaitingOcr ? (
          <p className="text-dark-6">
            Analyse en cours… recharge la page dans quelques instants.
          </p>
        ) : (
          <p className="text-dark-6">
            Aucun article n&apos;a pu être extrait de ce ticket.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-[10px] bg-white shadow-1 dark:bg-gray-dark">
      <div className="flex items-center justify-between gap-3 border-b border-stroke p-4 dark:border-dark-3">
        <h3 className="text-heading-6 font-bold text-dark dark:text-white">
          Articles ({drafts.length})
        </h3>
        {isValidated ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-green-light-7 px-3 py-1 text-xs font-medium text-green">
            ✓ Ticket validé
          </span>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={isPending}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPending
              ? "Enregistrement…"
              : dirtyCount > 0
              ? `Confirmer (${dirtyCount} correction${dirtyCount > 1 ? "s" : ""})`
              : "Confirmer le ticket"}
          </button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-stroke text-left text-xs uppercase text-dark-6 dark:border-dark-3">
            <tr>
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-4 py-3 font-medium">Texte brut</th>
              <th className="px-4 py-3 font-medium">Produit</th>
              <th className="px-4 py-3 font-medium">EAN</th>
              <th className="px-4 py-3 font-medium">Qté</th>
              <th className="px-4 py-3 font-medium text-right">Prix (€)</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-stroke dark:divide-dark-3">
            {drafts.map((d) => {
              const original = initialItems.find((i) => i.id === d.id)!;
              return (
                <tr
                  key={d.id}
                  className={
                    d.dirty ? "bg-yellow-light/10 dark:bg-yellow-dark/10" : ""
                  }
                >
                  <td className="px-4 py-3 text-dark-6">{original.line_index}</td>
                  <td className="px-4 py-3 max-w-[200px]">
                    <div className="truncate font-mono text-xs text-dark-6">
                      {original.raw_text}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <input
                      className="w-full rounded border border-stroke bg-transparent px-2 py-1 text-sm dark:border-dark-3"
                      value={d.produit_nom}
                      onChange={(e) =>
                        update(d.id, { produit_nom: e.target.value })
                      }
                      placeholder="—"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <input
                      className="w-32 rounded border border-stroke bg-transparent px-2 py-1 font-mono text-xs dark:border-dark-3"
                      value={d.ean}
                      onChange={(e) => update(d.id, { ean: e.target.value })}
                      placeholder="EAN13"
                      maxLength={13}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      className="w-20 rounded border border-stroke bg-transparent px-2 py-1 text-sm dark:border-dark-3"
                      value={d.quantity}
                      onChange={(e) =>
                        update(d.id, { quantity: e.target.value })
                      }
                    />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      className="w-24 rounded border border-stroke bg-transparent px-2 py-1 text-right text-sm dark:border-dark-3"
                      value={d.price_eur}
                      onChange={(e) =>
                        update(d.id, { price_eur: e.target.value })
                      }
                    />
                  </td>
                  <td className="px-4 py-3">
                    {original.validated_by_user ? (
                      <span className="text-xs text-green">✓ Validé</span>
                    ) : original.needs_validation ? (
                      <span className="text-xs text-orange-light">À valider</span>
                    ) : (
                      <span className="text-xs text-dark-6">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function toDraft(p: PrixExtrait): Draft {
  return {
    id: p.id,
    ean: p.ean ?? "",
    produit_nom: p.produit_nom ?? "",
    quantity: p.quantity != null ? String(p.quantity) : "",
    price_eur:
      p.price_eur != null
        ? String(p.price_eur)
        : p.line_total != null
        ? String(p.line_total)
        : p.unit_price != null
        ? String(p.unit_price)
        : "",
    dirty: false,
  };
}

function emptyToNull(s: string): string | null {
  const trimmed = s.trim();
  return trimmed === "" ? null : trimmed;
}

function parseNumberOrNull(s: string): number | null {
  const trimmed = s.trim();
  if (trimmed === "") return null;
  const n = Number.parseFloat(trimmed);
  return Number.isFinite(n) ? n : null;
}
