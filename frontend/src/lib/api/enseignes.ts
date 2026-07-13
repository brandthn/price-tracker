import { apiFetch } from "./client";
import type { EnseigneDetailOut, EnseignesOut } from "./types";

export function getEnseignes(
  opts: { minMatched?: number; windowWeeks?: number } = {},
): Promise<EnseignesOut> {
  const params = new URLSearchParams();
  if (opts.windowWeeks != null) params.set("window_weeks", String(opts.windowWeeks));
  if (opts.minMatched != null) params.set("min_matched", String(opts.minMatched));
  const qs = params.toString();
  return apiFetch<EnseignesOut>(`/enseignes${qs ? `?${qs}` : ""}`);
}

export function getEnseigneDetail(nom: string): Promise<EnseigneDetailOut> {
  return apiFetch<EnseigneDetailOut>(`/enseignes/${encodeURIComponent(nom)}`);
}
