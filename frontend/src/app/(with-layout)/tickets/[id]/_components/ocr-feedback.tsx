"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { getTicket, submitFeedback } from "@/lib/api/tickets";
import type { FeedbackRating } from "@/lib/api/types";

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 20; // ~60s max d'attente du re-OCR tier-2

export function OcrFeedback({
  ticketId,
  initialFeedback,
  initialAttempts,
}: {
  ticketId: string;
  initialFeedback: FeedbackRating | null;
  initialAttempts: number;
}) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<FeedbackRating | null>(
    initialFeedback,
  );
  const [busy, setBusy] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);

  const send = async (rating: FeedbackRating) => {
    if (busy || reanalyzing) return;
    setBusy(true);
    const previous = feedback;
    setFeedback(rating); // optimiste
    try {
      const res = await submitFeedback(ticketId, rating);
      if (res.retry_triggered) {
        toast.info("Merci ! Une nouvelle analyse plus poussée est lancée…");
        await pollUntilReanalyzed(ticketId, initialAttempts, setReanalyzing);
        router.refresh();
      } else if (rating === "up") {
        toast.success("Merci pour votre retour 👍");
      } else {
        toast.info(
          "Retour enregistré. Ce ticket a déjà été ré-analysé au maximum.",
        );
      }
    } catch (err) {
      setFeedback(previous); // rollback
      toast.error(`Impossible d'enregistrer l'avis : ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark">
      <h3 className="mb-1 text-sm font-semibold uppercase text-dark-6">
        Cette lecture est-elle correcte ?
      </h3>
      <p className="mb-3 text-xs text-dark-6">
        Votre avis aide le système à s&apos;améliorer. Le ticket est pris en
        compte quoi qu&apos;il arrive.
      </p>

      {reanalyzing ? (
        <p className="text-sm text-primary">Nouvelle analyse en cours…</p>
      ) : (
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => send("up")}
            disabled={busy}
            aria-pressed={feedback === "up"}
            className={btnClass(feedback === "up", "up")}
          >
            👍 Correct
          </button>
          <button
            type="button"
            onClick={() => send("down")}
            disabled={busy}
            aria-pressed={feedback === "down"}
            className={btnClass(feedback === "down", "down")}
          >
            👎 À revoir
          </button>
        </div>
      )}
    </div>
  );
}

function btnClass(active: boolean, kind: FeedbackRating): string {
  const base =
    "flex-1 rounded-lg border px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50";
  if (!active) {
    return `${base} border-stroke text-dark hover:bg-gray-1 dark:border-dark-3 dark:text-white dark:hover:bg-dark-2`;
  }
  return kind === "up"
    ? `${base} border-green bg-green-light-7 text-green`
    : `${base} border-red bg-red-light-6 text-red`;
}

async function pollUntilReanalyzed(
  ticketId: string,
  baselineAttempts: number,
  setReanalyzing: (v: boolean) => void,
): Promise<void> {
  setReanalyzing(true);
  try {
    for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
      await sleep(POLL_INTERVAL_MS);
      try {
        const t = await getTicket(ticketId);
        if (t.ocr_attempts > baselineAttempts && t.status === "ocr_done") {
          return;
        }
      } catch {
        // transient — on retente au tick suivant
      }
    }
  } finally {
    setReanalyzing(false);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
