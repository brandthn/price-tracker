import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-light/30 text-orange-light-1",
  processing: "bg-blue-light/30 text-primary",
  ocr_processing: "bg-blue-light/30 text-primary",
  ocr_done: "bg-green-light-7 text-green",
  ocr_failed: "bg-red-light-6 text-red",
  validated: "bg-green-light-7 text-green",
};

// pas d'étape "à valider" côté user, un ticket analysé compte direct
const STATUS_LABELS: Record<string, string> = {
  pending: "En attente",
  processing: "Analyse…",
  ocr_processing: "Analyse…",
  ocr_done: "Pris en compte",
  ocr_failed: "Échec OCR",
  validated: "Pris en compte",
};

export function StatusBadge({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  const style = STATUS_STYLES[status] ?? "bg-gray-2 text-dark-6";
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium",
        style,
      )}
    >
      {label}
    </span>
  );
}
