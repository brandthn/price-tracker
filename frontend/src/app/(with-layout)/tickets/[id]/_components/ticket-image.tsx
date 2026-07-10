"use client";

import { useEffect, useState } from "react";
import { getTicketImageURL } from "@/lib/api/tickets";

type State =
  | { kind: "loading" }
  | { kind: "ready"; url: string }
  | { kind: "error" };

export function TicketImage({ ticketId }: { ticketId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    getTicketImageURL(ticketId)
      .then((res) => {
        if (active) setState({ kind: "ready", url: res.read_url });
      })
      .catch(() => {
        if (active) setState({ kind: "error" });
      });
    return () => {
      active = false;
    };
  }, [ticketId]);

  return (
    <div className="rounded-[10px] bg-white p-3 shadow-1 dark:bg-gray-dark">
      <h3 className="mb-2 px-2 pt-1 text-sm font-semibold uppercase text-dark-6">
        Ticket
      </h3>
      <div className="flex min-h-[220px] items-center justify-center overflow-hidden rounded-md bg-gray-1 dark:bg-dark-2">
        {state.kind === "loading" && (
          <span className="text-sm text-dark-6">Chargement de l&apos;image…</span>
        )}
        {state.kind === "error" && (
          <span className="px-4 py-8 text-center text-sm text-dark-6">
            Image indisponible.
          </span>
        )}
        {state.kind === "ready" && (
          <a href={state.url} target="_blank" rel="noopener noreferrer">
            {/* Signed GCS URL (blob distant) — pas de next/image. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={state.url}
              alt="Photo du ticket de caisse"
              className="max-h-[70vh] w-full object-contain"
            />
          </a>
        )}
      </div>
    </div>
  );
}
