"use client";

// asset généré par scripts/build-france-map.mjs
// echelle bleu/gris/rouge et pas rouge/vert (deuteranopie), + valeur signée
// au survol: la couleur ne porte jamais le sens toute seule

import { useState } from "react";
import franceMap from "@/assets/france-departements.json";
import type { MapDepartementValue } from "@/lib/api/types";
import { formatPct } from "@/lib/format-fr";

type Departement = { code: string; nom: string; d: string };

const BINS = [
  { max: -3, varName: "--viz-map-down-3", label: "≤ −3 %" },
  { max: -1, varName: "--viz-map-down-2", label: "−3 à −1 %" },
  { max: -0.25, varName: "--viz-map-down-1", label: "−1 à −0,25 %" },
  { max: 0.25, varName: "--viz-map-zero", label: "stable" },
  { max: 1, varName: "--viz-map-up-1", label: "+0,25 à +1 %" },
  { max: 3, varName: "--viz-map-up-2", label: "+1 à +3 %" },
  { max: Infinity, varName: "--viz-map-up-3", label: "≥ +3 %" },
] as const;

function binFor(pct: number) {
  return BINS.find((b) => pct <= b.max) ?? BINS[BINS.length - 1];
}

type Hovered = {
  code: string;
  nom: string;
  pct: number | null;
  sampleSize: number | null;
  x: number;
  y: number;
};

export function FranceMap({ values }: { values: MapDepartementValue[] }) {
  const [hovered, setHovered] = useState<Hovered | null>(null);

  const byDept = new Map(values.map((v) => [v.departement, v]));
  const departements = franceMap.departements as Departement[];

  const onEnter = (
    e: React.PointerEvent<SVGPathElement>,
    dept: Departement,
  ) => {
    const container = e.currentTarget.ownerSVGElement?.parentElement;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const v = byDept.get(dept.code);
    setHovered({
      code: dept.code,
      nom: dept.nom,
      pct: v?.inflation_pct ?? null,
      sampleSize: v?.sample_size ?? null,
      x: ((e.clientX - rect.left) / rect.width) * 100,
      y: ((e.clientY - rect.top) / rect.height) * 100,
    });
  };

  return (
    <div className="relative">
      <svg
        viewBox={franceMap.viewBox}
        className="w-full"
        role="img"
        aria-label="Carte de France : variation des prix par département"
      >
        {departements.map((dept) => {
          const v = byDept.get(dept.code);
          const fill =
            v?.inflation_pct != null
              ? `var(${binFor(v.inflation_pct).varName})`
              : "var(--viz-map-empty)";
          return (
            <path
              key={dept.code}
              d={dept.d}
              fill={fill}
              stroke="var(--viz-map-stroke)"
              strokeWidth={0.6}
              className="transition-opacity hover:opacity-75"
              onPointerEnter={(e) => onEnter(e, dept)}
              onPointerMove={(e) => onEnter(e, dept)}
              onPointerLeave={() => setHovered(null)}
            />
          );
        })}
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg bg-dark px-3 py-2 text-xs text-white shadow-lg dark:bg-white dark:text-dark"
          style={{
            left: `${Math.min(hovered.x, 70)}%`,
            top: `${hovered.y}%`,
            transform: "translate(8px, -110%)",
          }}
        >
          <div className="font-semibold">
            {hovered.nom} ({hovered.code})
          </div>
          {hovered.pct != null ? (
            <div className="opacity-80">
              {formatPct(hovered.pct)} sur 4 semaines
              {hovered.sampleSize != null && (
                <> · {hovered.sampleSize.toLocaleString("fr-FR")} relevés</>
              )}
            </div>
          ) : (
            <div className="opacity-80">Pas encore assez de relevés</div>
          )}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-dark-5 dark:text-dark-6">
        {BINS.map((b) => (
          <span key={b.varName} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className="size-3 rounded-sm"
              style={{ background: `var(${b.varName})` }}
            />
            {b.label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-3 rounded-sm"
            style={{ background: "var(--viz-map-empty)" }}
          />
          pas de données
        </span>
      </div>
    </div>
  );
}
