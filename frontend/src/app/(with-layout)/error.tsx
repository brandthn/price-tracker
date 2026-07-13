"use client";

// sans ce fichier une erreur RSC (401 token expiré, refetch raté) = page blanche

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
    console.error("[ui-error]", error);
  }, [error]);

  // reset() seul ne refetch pas les RSC -> l'erreur revient. les 2 dans la meme transition
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
          {/* <a> et pas <Link>: si l'erreur est sur / la nav client est un no-op
              et ressert le payload en erreur depuis le cache router */}
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
