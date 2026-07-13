"use client";

// erreurs du layout racine (error.tsx ne couvre pas ce cas)
// doit rendre ses propres html/body: il remplace le layout

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[global-ui-error]", error);
  }, [error]);

  return (
    <html lang="fr">
      <body>
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: "1rem",
            fontFamily: "system-ui, sans-serif",
            padding: "2rem",
            textAlign: "center",
          }}
        >
          <h1 style={{ fontSize: "1.25rem", fontWeight: 700 }}>
            PriceTracker a rencontré une erreur
          </h1>
          <p style={{ color: "#64748b", maxWidth: "28rem" }}>
            Rechargez la page pour continuer.
          </p>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              background: "#5750F1",
              color: "white",
              border: "none",
              borderRadius: "0.5rem",
              padding: "0.625rem 1.25rem",
              fontSize: "0.875rem",
              cursor: "pointer",
            }}
          >
            Recharger
          </button>
        </div>
      </body>
    </html>
  );
}
