import { apiFetch } from "./client";
import type { InflationIndex, RankingsOut } from "./types";

export function getNationalIndex(): Promise<InflationIndex> {
  return apiFetch<InflationIndex>("/indices/national");
}

export function getRegionalIndex(dept: string): Promise<InflationIndex> {
  return apiFetch<InflationIndex>(
    `/indices/regional/${encodeURIComponent(dept)}`,
  );
}

export function getRankings(limit = 20): Promise<RankingsOut> {
  return apiFetch<RankingsOut>(`/observatoire/rankings?limit=${limit}`);
}

export function getHallOfShame(limit = 20): Promise<RankingsOut> {
  return apiFetch<RankingsOut>(`/observatoire/hall-of-shame?limit=${limit}`);
}
