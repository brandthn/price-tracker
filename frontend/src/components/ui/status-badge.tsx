import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-yellow-light/30 text-orange-light-1",
  processing: "bg-blue-light/30 text-primary",
  ocr_done: "bg-blue-light-2/30 text-primary",
  ocr_failed: "bg-red-light-6 text-red",
  validated: "bg-green-light-7 text-green",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "En attente",
  processing: "Traitement",
  ocr_done: "OCR terminé",
  ocr_failed: "Échec OCR",
  validated: "Validé",
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
