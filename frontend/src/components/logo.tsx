export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <span
        aria-hidden
        className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary font-bold text-white"
      >
        {/* Mini-courbe : les prix qui bougent, en un glyphe */}
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <path
            d="M2.5 14.5L7 9.5l3.5 3L17.5 5"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="17.5" cy="5" r="2" fill="currentColor" />
        </svg>
      </span>
      <div className="leading-tight">
        <div className="text-base font-bold text-dark dark:text-white">
          PriceTracker
        </div>
        <div className="text-xs text-dark-5 dark:text-dark-6">
          L&apos;inflation, vue de votre caddie
        </div>
      </div>
    </div>
  );
}
