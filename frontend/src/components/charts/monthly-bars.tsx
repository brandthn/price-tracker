"use client";

// Colonnes des dépenses mensuelles — série unique séquentielle (accent de
// marque), barres ≤24px à sommet arrondi 4px / base carrée, survol = tooltip.
// Seule la dernière colonne porte un label direct ; l'axe Y fait le reste.

import { useState } from "react";
import { formatEuro, formatMonth } from "@/lib/format-fr";
import type { BasketMonth } from "@/lib/api/types";

const W = 640;
const H = 220;
const PAD = { top: 18, right: 12, bottom: 26, left: 52 };

export function MonthlyBars({ months }: { months: BasketMonth[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (months.length === 0) return null;

  const max = Math.max(...months.map((m) => m.total_eur)) * 1.15;
  const usableW = W - PAD.left - PAD.right;
  const usableH = H - PAD.top - PAD.bottom;
  const band = usableW / months.length;
  const barW = Math.min(24, band * 0.6);

  const x = (i: number) => PAD.left + band * i + (band - barW) / 2;
  const y = (v: number) => PAD.top + (1 - v / max) * usableH;

  const ticks = [max / 3, (2 * max) / 3, max].map((t) => Math.round(t));
  const last = months.length - 1;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="Dépenses par mois"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--viz-grid)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(t) + 3.5}
              textAnchor="end"
              fontSize={11}
              fill="var(--viz-ink-2)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {t.toLocaleString("fr-FR")} €
            </text>
          </g>
        ))}

        {months.map((m, i) => {
          const barH = Math.max(2, PAD.top + usableH - y(m.total_eur));
          const r = Math.min(4, barW / 2, barH);
          const top = y(m.total_eur);
          // Sommet arrondi, base carrée.
          const d = `M${x(i)},${top + r}
            a${r},${r} 0 0 1 ${r},-${r}
            h${barW - 2 * r}
            a${r},${r} 0 0 1 ${r},${r}
            v${barH - r}
            h${-barW}Z`;
          return (
            <g key={m.month}>
              <path
                d={d}
                fill="var(--viz-line)"
                opacity={hover === null || hover === i ? 1 : 0.45}
                onPointerEnter={() => setHover(i)}
                onPointerLeave={() => setHover(null)}
              />
              <text
                x={x(i) + barW / 2}
                y={H - 8}
                textAnchor="middle"
                fontSize={11}
                fill="var(--viz-ink-2)"
              >
                {formatMonth(m.month)}
              </text>
            </g>
          );
        })}

        {/* label direct sur la dernière colonne uniquement */}
        <text
          x={x(last) + barW / 2}
          y={y(months[last].total_eur) - 6}
          textAnchor="middle"
          fontSize={12}
          fontWeight={600}
          fill="var(--viz-ink)"
        >
          {formatEuro(months[last].total_eur)}
        </text>
      </svg>

      {hover !== null && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg bg-dark px-3 py-2 text-xs text-white shadow-lg dark:bg-white dark:text-dark"
          style={{
            left: `${((x(hover) + barW / 2) / W) * 100}%`,
            top: `${(y(months[hover].total_eur) / H) * 100}%`,
            transform: "translate(-50%, -110%)",
          }}
        >
          <div className="font-semibold">
            {formatEuro(months[hover].total_eur)}
          </div>
          <div className="opacity-70">
            {formatMonth(months[hover].month)} · {months[hover].tickets}{" "}
            ticket{months[hover].tickets > 1 ? "s" : ""}
          </div>
        </div>
      )}
    </div>
  );
}
