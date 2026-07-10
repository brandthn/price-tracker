"use client";

// Courbe de tendance (série unique) — SVG maison, sans lib.
// Specs dataviz : ligne 2px arrondie, nappe ~8-10% d'opacité, point terminal
// ≥8px avec anneau surface 2px, grilles hairline recessives, crosshair +
// tooltip au survol, label direct sur le dernier point uniquement.
// Série unique → pas de légende (le titre de la section nomme la série).

import { useMemo, useRef, useState } from "react";
import { formatDateShort, formatEuro } from "@/lib/format-fr";

export type TrendPoint = {
  date: string;
  value: number;
  sampleSize?: number | null;
};

// Le format est un descripteur sérialisable, PAS une fonction : ce composant
// est un client component appelé depuis des server components, et React ne
// peut pas sérialiser une fonction à travers la frontière RSC.
export type TrendUnit = "index" | "eur";

type Props = {
  points: TrendPoint[];
  unit: TrendUnit;
  // Ligne de référence horizontale (ex : base 100 d'un indice).
  baseline?: number;
  sampleLabel?: string; // ex : "relevés" — affiché dans le tooltip
  height?: number;
  ariaLabel: string;
};

function formatValue(v: number, unit: TrendUnit): string {
  return unit === "eur"
    ? formatEuro(v)
    : v.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
}

const W = 640;
const PAD = { top: 18, right: 20, bottom: 26, left: 46 };

export function TrendChart({
  points,
  unit,
  baseline,
  sampleLabel = "relevés",
  height = 240,
  ariaLabel,
}: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const H = height;
  const geom = useMemo(() => {
    const values = points.map((p) => p.value);
    const withBaseline =
      baseline != null ? [...values, baseline] : values;
    let min = Math.min(...withBaseline);
    let max = Math.max(...withBaseline);
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const pad = (max - min) * 0.12;
    min -= pad;
    max += pad;

    const x = (i: number) =>
      points.length === 1
        ? (PAD.left + W - PAD.right) / 2
        : PAD.left + (i / (points.length - 1)) * (W - PAD.left - PAD.right);
    const y = (v: number) =>
      PAD.top + (1 - (v - min) / (max - min)) * (H - PAD.top - PAD.bottom);

    const line = points
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
      .join("");
    const area =
      line +
      `L${x(points.length - 1).toFixed(1)},${(H - PAD.bottom).toFixed(1)}` +
      `L${x(0).toFixed(1)},${(H - PAD.bottom).toFixed(1)}Z`;

    // 3 ticks Y "propres" dans le domaine.
    const ticks: number[] = [];
    const step = niceStep((max - min) / 3);
    for (let t = Math.ceil(min / step) * step; t <= max; t += step) {
      ticks.push(t);
    }
    return { x, y, line, area, ticks, min, max };
  }, [points, baseline, H]);

  if (points.length === 0) return null;

  const last = points[points.length - 1];

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const usable = W - PAD.left - PAD.right;
    const ratio = Math.min(1, Math.max(0, (px - PAD.left) / usable));
    setHover(Math.round(ratio * (points.length - 1)));
  };

  const hovered = hover != null ? points[hover] : null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={ariaLabel}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {/* grilles hairline */}
        {geom.ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={geom.y(t)}
              y2={geom.y(t)}
              stroke="var(--viz-grid)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={geom.y(t) + 3.5}
              textAnchor="end"
              fontSize={11}
              fill="var(--viz-ink-2)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {Math.round(t) === t ? t : t.toFixed(1)}
            </text>
          </g>
        ))}

        {/* baseline (ex : base 100) */}
        {baseline != null && (
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={geom.y(baseline)}
            y2={geom.y(baseline)}
            stroke="var(--viz-axis)"
            strokeWidth={1}
          />
        )}

        {/* nappe + ligne */}
        <path d={geom.area} fill="var(--viz-area)" />
        <path
          d={geom.line}
          fill="none"
          stroke="var(--viz-line)"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* crosshair au survol */}
        {hovered && hover != null && (
          <g>
            <line
              x1={geom.x(hover)}
              x2={geom.x(hover)}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="var(--viz-axis)"
              strokeWidth={1}
            />
            <circle
              cx={geom.x(hover)}
              cy={geom.y(hovered.value)}
              r={4.5}
              fill="var(--viz-line)"
              stroke="var(--viz-surface)"
              strokeWidth={2}
            />
          </g>
        )}

        {/* point terminal + label direct (le seul labellisé) */}
        <circle
          cx={geom.x(points.length - 1)}
          cy={geom.y(last.value)}
          r={4.5}
          fill="var(--viz-line)"
          stroke="var(--viz-surface)"
          strokeWidth={2}
        />
        <text
          x={Math.min(geom.x(points.length - 1) + 8, W - 2)}
          y={geom.y(last.value) - 8}
          textAnchor="end"
          fontSize={12}
          fontWeight={600}
          fill="var(--viz-ink)"
        >
          {formatValue(last.value, unit)}
        </text>

        {/* ticks X : premier / milieu / dernier */}
        {[0, Math.floor((points.length - 1) / 2), points.length - 1]
          .filter((v, i, a) => a.indexOf(v) === i)
          .map((i) => (
            <text
              key={i}
              x={geom.x(i)}
              y={H - 8}
              textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
              fontSize={11}
              fill="var(--viz-ink-2)"
            >
              {formatDateShort(points[i].date)}
            </text>
          ))}
      </svg>

      {/* tooltip HTML positionné en % (suit le responsive du SVG) */}
      {hovered && hover != null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-lg bg-dark px-3 py-2 text-xs text-white shadow-lg dark:bg-white dark:text-dark"
          style={{
            left: `${(geom.x(hover) / W) * 100}%`,
            top: `${(Math.max(geom.y(hovered.value) - 14, 0) / H) * 100}%`,
            transform: "translate(-50%, -100%)",
          }}
        >
          <div className="font-semibold">{formatValue(hovered.value, unit)}</div>
          <div className="opacity-70">
            {formatDateShort(hovered.date)}
            {hovered.sampleSize != null && (
              <> · {hovered.sampleSize.toLocaleString("fr-FR")} {sampleLabel}</>
            )}
          </div>
        </div>
      )}

      {/* Vue table (accessibilité) */}
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <thead>
          <tr>
            <th>Date</th>
            <th>Valeur</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.date}>
              <td>{p.date}</td>
              <td>{formatValue(p.value, unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function niceStep(raw: number): number {
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const norm = raw / mag;
  if (norm <= 1) return mag;
  if (norm <= 2) return 2 * mag;
  if (norm <= 5) return 5 * mag;
  return 10 * mag;
}
