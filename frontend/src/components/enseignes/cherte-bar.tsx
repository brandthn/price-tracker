// Barre de cherté relative, centrée sur 100 (le niveau médian des enseignes).
// Segment vers la DROITE en rouge si > 100 (plus chère), vers la GAUCHE en vert
// si < 100 (moins chère) — même sémantique prix que DeltaPill. Server component,
// aucune interactivité. L'échelle est fixe (±SPAN autour de 100) et le marqueur
// est clampé aux bords ; le chiffre exact reste porté par le libellé voisin.

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
      {/* repère central : la médiane (100) */}
      <span className="absolute left-1/2 top-1/2 h-3.5 w-px -translate-x-1/2 -translate-y-1/2 bg-dark-5/40 dark:bg-dark-6/50" />

      {/* segment coloré entre le centre et la valeur */}
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

      {/* marqueur de position */}
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
