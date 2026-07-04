import type { ReactNode } from "react";

// Tuile statistique : label + valeur (chiffres proportionnels, pas de
// tabular-nums sur un grand nombre isolé) + contexte optionnel (delta,
// mention d'échantillon…).
export function StatTile({
  label,
  value,
  context,
}: {
  label: string;
  value: ReactNode;
  context?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-stroke bg-white p-5 dark:border-dark-3 dark:bg-gray-dark">
      <div className="text-sm text-dark-5 dark:text-dark-6">{label}</div>
      <div className="mt-1.5 text-heading-6 font-bold text-dark dark:text-white">
        {value}
      </div>
      {context && (
        <div className="mt-1 flex items-center gap-2 text-xs text-dark-5 dark:text-dark-6">
          {context}
        </div>
      )}
    </div>
  );
}
