"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";
import type { Granularity } from "@/lib/api/indices";

// l'état vit dans l'URL (?g=) pour survivre au refresh et au partage de lien
const OPTIONS: { value: Granularity; label: string }[] = [
  { value: "week", label: "Semaine" },
  { value: "month", label: "Mois" },
];

export function GranularityToggle({ value }: { value: Granularity }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [isPending, startTransition] = useTransition();

  function select(next: Granularity) {
    if (next === value) return;
    const qs = new URLSearchParams(params);
    if (next === "week") qs.delete("g");
    else qs.set("g", next);
    const query = qs.toString();
    startTransition(() => {
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    });
  }

  return (
    <div
      role="group"
      aria-label="Granularité temporelle"
      className={`inline-flex rounded-xl border border-stroke bg-white p-0.5 dark:border-dark-3 dark:bg-gray-dark ${
        isPending ? "opacity-70" : ""
      }`}
    >
      {OPTIONS.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => select(opt.value)}
            className={`rounded-[10px] px-4 py-1.5 text-sm font-medium transition-colors ${
              active
                ? "bg-primary text-white"
                : "text-dark-5 hover:text-dark dark:text-dark-6 dark:hover:text-white"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
