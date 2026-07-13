// centrée sur 100 = médiane des enseignes. échelle fixe (SPAN), marqueur clampé
// aux bords, le chiffre exact est dans le libellé à coté

const SPAN = 20; // demi-amplitude visuelle : [80 … 120]

export function CherteBar({ index }: { index: number }) {
  const flat = Math.abs(index - 100) < 0.5;
  const above = index > 100;

  const clamped = Math.max(100 - SPAN, Math.min(100 + SPAN, index));
  const posPct = ((clamped - (100 - SPAN)) / (2 * SPAN)) * 100; // 0 … 100
  const segLeft = Math.min(50, posPct);
  const segWidth = Math.abs(posPct - 50);

  return (
    <div
      className="relative h-2 w-full rounded-full bg-gray-2 dark:bg-dark-3"
      role="img"
      aria-label={
        flat
          ? "Au niveau médian des enseignes"
          : above
            ? `${Math.round(index - 100)} % au-dessus de la médiane`
            : `${Math.round(100 - index)} % en dessous de la médiane`
      }
    >
      <span className="absolute left-1/2 top-1/2 h-3.5 w-px -translate-x-1/2 -translate-y-1/2 bg-dark-5/40 dark:bg-dark-6/50" />

      {!flat && (
        <span
          className="absolute top-0 h-2 rounded-full"
          style={{
            left: `${segLeft}%`,
            width: `${segWidth}%`,
            background: above ? "var(--viz-up-bg)" : "var(--viz-down-bg)",
          }}
        />
      )}

      <span
        className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white dark:border-gray-dark"
        style={{
          left: `${posPct}%`,
          background: flat
            ? "var(--viz-ink-2)"
            : above
              ? "var(--viz-up-text)"
              : "var(--viz-down-text)",
        }}
      />
    </div>
  );
}
