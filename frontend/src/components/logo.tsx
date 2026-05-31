export function Logo() {
  return (
    <div className="flex items-center gap-2">
      <span
        aria-hidden
        className="grid size-8 place-items-center rounded-lg bg-primary text-white font-bold"
      >
        €
      </span>
      <div className="leading-tight">
        <div className="text-base font-bold text-dark dark:text-white">
          PriceTracker
        </div>
        <div className="text-xs text-dark-5 dark:text-dark-6">
          Observatoire des prix
        </div>
      </div>
    </div>
  );
}
