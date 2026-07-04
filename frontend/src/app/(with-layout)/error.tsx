"use client";

// Error boundary des pages authentifiées (App Router). Sans ce fichier, toute
// erreur levée dans un Server Component (ex: re-fetch d'un ticket qui rate
// pendant un `router.refresh()`, ou token Firebase expiré → 401) faisait tomber
// l'app en PAGE BLANCHE. Ici on dégrade proprement avec un bouton « Réessayer ».

import { startTransition, useEffect } from "react";
import { useRouter } from "next/navigation";

export default function WithLayoutError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();

  useEffect(() => {
    // Visible dans la console navigateur + remonté côté Cloud Run via le digest.
    console.error("[ui-error]", error);
  }, [error]);

  // `reset()` seul ne re-render que l'arbre client : sans `router.refresh()`
  // les Server Components ne sont pas re-fetchés et l'erreur revient à
  // l'identique. Les deux doivent partir dans la même transition.
  const retry = () => {
    startTransition(() => {
      router.refresh();
      reset();
    });
  };

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <div className="rounded-[10px] bg-white p-8 shadow-1 dark:bg-gray-dark">
        <h1 className="mb-2 text-heading-5 font-bold text-dark dark:text-white">
          Un souci d&apos;affichage est survenu
        </h1>
        <p className="mb-6 max-w-md text-sm text-dark-6">
          La page n&apos;a pas pu se recharger correctement. Vos données ne sont
          pas perdues — réessayez, ou revenez à l&apos;accueil.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={retry}
            className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white hover:opacity-90"
          >
            Réessayer
          </button>
          {/* <a> volontaire (pas <Link>) : quand l'erreur touche `/` lui-même,
              une navigation client vers la même route est un no-op et resert
              le payload en erreur depuis le cache du router. Le rechargement
              complet est la porte de sortie garantie. */}
          <a
            href="/"
            className="rounded-lg border border-stroke px-5 py-2.5 text-sm font-medium text-dark hover:bg-gray-1 dark:border-dark-3 dark:text-white dark:hover:bg-dark-2"
          >
            Retour à l&apos;accueil
          </a>
        </div>
      </div>
    </div>
  );
}
