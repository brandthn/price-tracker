// une variation garde toujours son signe: la couleur seule ne suffit pas (daltonisme)

const EUR = new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency: "EUR",
});

const NUM = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

export function formatEuro(value: number): string {
  return EUR.format(value);
}

export function formatNumber(value: number): string {
  return NUM.format(value);
}

export function formatPct(value: number, decimals = 1): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("fr-FR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} %`;
}

export function formatDateShort(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

export function formatMonth(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
}

export function formatDateLong(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
