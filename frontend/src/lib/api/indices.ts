import { apiFetch } from "./client";
import type { InflationIndex, MapOut, RankingsOut } from "./types";

export function getNationalIndex(): Promise<InflationIndex> {
  return apiFetch<InflationIndex>("/indices/national");
}

export function getRegionalIndex(dept: string): Promise<InflationIndex> {
  return apiFetch<InflationIndex>(
    `/indices/regional/${encodeURIComponent(dept)}`,
  );
}

export function getRankings(
  limit = 20,
  direction: "up" | "down" = "up",
): Promise<RankingsOut> {
  return apiFetch<RankingsOut>(
    `/observatoire/rankings?limit=${limit}&direction=${direction}`,
  );
}

export function getHallOfShame(limit = 20): Promise<RankingsOut> {
  return apiFetch<RankingsOut>(`/observatoire/hall-of-shame?limit=${limit}`);
}

export function getInflationMap(): Promise<MapOut> {
  return apiFetch<MapOut>("/observatoire/map");
}
