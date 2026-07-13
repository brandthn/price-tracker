import { cn } from "@/lib/utils";
import { formatPct } from "@/lib/format-fr";

// le signe est toujours affiché, jamais la couleur seule (daltonisme)
export function DeltaPill({
  pct,
  className,
}: {
  pct: number;
  className?: string;
}) {
  const up = pct > 0;
  const flat = Math.abs(pct) < 0.05;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        className,
      )}
      style={
        flat
          ? { background: "var(--viz-map-zero)", color: "var(--viz-ink-2)" }
          : {
              background: up ? "var(--viz-up-bg)" : "var(--viz-down-bg)",
              color: up ? "var(--viz-up-text)" : "var(--viz-down-text)",
            }
      }
    >
      {formatPct(pct)}
    </span>
  );
}
