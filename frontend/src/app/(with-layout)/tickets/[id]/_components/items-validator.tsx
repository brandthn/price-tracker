"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { patchTicketItems } from "@/lib/api/tickets";
import type { PrixExtrait } from "@/lib/api/types";

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
  ocrAttempts,
}: {
  ticketId: string;
  initialItems: PrixExtrait[];
  ticketStatus: string;
  ocrAttempts: number;
}) {
  const router = useRouter();
  const [drafts, setDrafts] = useState<Draft[]>(() =>
    initialItems.map(toDraft),
  );
  const [isPending, startTransition] = useTransition();

  // resync des brouillons uniquement quand ocr_attempts bouge, sinon on écraserait
  // la saisie en cours à chaque refresh
  useEffect(() => {
    setDrafts(initialItems.map(toDraft));
    // initialItems hors deps exprès (cf. au dessus)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ocrAttempts]);

  const dirtyCount = useMemo(
    () => drafts.filter((d) => d.dirty).length,
    [drafts],
  );

  // le prix d'une ligne est déjà le montant payé, pas un unitaire à multiplier
  const liveTotal = useMemo(
    () =>
      drafts.reduce((acc, d) => {
        const n = Number.parseFloat(d.price_eur.replace(",", "."));
        return acc + (Number.isFinite(n) ? n : 0);
      }, 0),
    [drafts],
  );
  const validatedCount = useMemo(
    () =>
      initialItems.filter((i) => i.validated_by_user).length,
    [initialItems],
  );

  const isEmpty = initialItems.length === 0;
  const isAwaitingOcr =
    ticketStatus === "pending" ||
    ticketStatus === "processing" ||
    ticketStatus === "ocr_processing";

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
          `${changed.length} correction${changed.length > 1 ? "s" : ""} enregistrée${changed.length > 1 ? "s" : ""}.`,
        );
        // une save ne bouge pas ocr_attempts donc pas de resync -> on clear dirty à la main
        setDrafts((prev) => prev.map((d) => ({ ...d, dirty: false })));
        router.refresh();
      } catch (err) {
        toast.error(`Impossible d'enregistrer : ${(err as Error).message}`);
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
            Lecture en cours. Rechargez la page dans quelques instants.
          </p>
        ) : (
          <p className="text-dark-6">
            Aucun article n&apos;a pu être lu sur ce ticket.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-[10px] bg-white shadow-1 dark:bg-gray-dark">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-stroke p-4 dark:border-dark-3">
        <div className="flex flex-wrap items-center gap-6">
          <Stat label="Total" value={`${liveTotal.toFixed(2)} €`} strong />
          <Stat label="Articles" value={String(drafts.length)} />
          <Stat label="Vérifiés" value={`${validatedCount}/${drafts.length}`} />
        </div>
        <button
          type="button"
          onClick={submit}
          disabled={isPending || dirtyCount === 0}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isPending
            ? "Enregistrement…"
            : dirtyCount > 0
            ? `Enregistrer (${dirtyCount} correction${dirtyCount > 1 ? "s" : ""})`
            : "Aucune correction"}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-stroke text-left text-xs uppercase text-dark-6 dark:border-dark-3">
            <tr>
              <th className="px-4 py-3 font-medium">Article</th>
              <th className="px-4 py-3 font-medium">EAN</th>
              <th className="px-4 py-3 font-medium">Qté</th>
              <th className="px-4 py-3 font-medium text-right">Prix payé (€)</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-stroke dark:divide-dark-3">
            {drafts.map((d) => {
              // ids réécrits après un re-OCR: on saute la ligne plutot que de crasher
              const original = initialItems.find((i) => i.id === d.id);
              if (!original) return null;
              return (
                <tr
                  key={d.id}
                  className={
                    d.dirty ? "bg-yellow-light/10 dark:bg-yellow-dark/10" : ""
                  }
                >
                  <td className="px-4 py-3 align-top">
                    <input
                      className="w-full min-w-[160px] rounded border border-stroke bg-transparent px-2 py-1 text-sm dark:border-dark-3"
                      value={d.produit_nom}
                      onChange={(e) =>
                        update(d.id, { produit_nom: e.target.value })
                      }
                      placeholder={original.raw_text || "Nom du produit"}
                    />
                    <div className="mt-1 truncate font-mono text-[11px] text-dark-6">
                      {original.raw_text}
                    </div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <input
                      className="w-32 rounded border border-stroke bg-transparent px-2 py-1 font-mono text-xs dark:border-dark-3"
                      value={d.ean}
                      onChange={(e) => update(d.id, { ean: e.target.value })}
                      placeholder="EAN13"
                      maxLength={13}
                    />
                  </td>
                  <td className="px-4 py-3 align-top">
                    <input
                      type="number"
                      step="0.001"
                      min="0"
                      className="w-20 rounded border border-stroke bg-transparent px-2 py-1 text-sm dark:border-dark-3"
                      value={d.quantity}
                      onChange={(e) =>
                        update(d.id, { quantity: e.target.value })
                      }
                    />
                  </td>
                  <td className="px-4 py-3 text-right align-top">
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
                  <td className="px-4 py-3 align-top">
                    {original.validated_by_user ? (
                      <span className="text-xs text-green">✓ Vérifié</span>
                    ) : original.needs_validation ? (
                      <span className="text-xs text-orange-light">À vérifier</span>
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

      <p className="border-t border-stroke px-4 py-3 text-xs text-dark-6 dark:border-dark-3">
        Le « prix payé » est le montant de la ligne tel qu&apos;imprimé sur le
        ticket (colonne Montant), pas le prix unitaire. Le total se recalcule à
        chaque correction.
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div>
      <div className="text-xs uppercase text-dark-6">{label}</div>
      <div
        className={
          strong
            ? "text-heading-6 font-bold text-dark dark:text-white"
            : "text-sm font-medium text-dark dark:text-white"
        }
      >
        {value}
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
  const trimmed = s.trim().replace(",", ".");
  if (trimmed === "") return null;
  const n = Number.parseFloat(trimmed);
  return Number.isFinite(n) ? n : null;
}
