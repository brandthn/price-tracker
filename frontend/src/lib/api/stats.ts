import { apiFetch } from "./client";
import type { BrandStats } from "./types";

export function getBrandStats(brand: string): Promise<BrandStats> {
  return apiFetch<BrandStats>(`/stats/brand/${encodeURIComponent(brand)}`);
}

export type { BrandStats };
