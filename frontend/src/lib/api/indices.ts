import { apiFetch } from "./client";
import type { InflationIndex, MapOut, RankingsOut } from "./types";

export type Granularity = "week" | "month";

export function getNationalIndex(
  granularity: Granularity = "week",
): Promise<InflationIndex> {
  return apiFetch<InflationIndex>(`/indices/national?granularity=${granularity}`);
}

export function getRegionalIndex(dept: string): Promise<InflationIndex> {
  return apiFetch<InflationIndex>(
    `/indices/regional/${encodeURIComponent(dept)}`,
  );
}

export function getRankings(
  limit = 20,
  direction: "up" | "down" = "up",
  granularity: Granularity = "week",
): Promise<RankingsOut> {
  return apiFetch<RankingsOut>(
    `/observatoire/rankings?limit=${limit}&direction=${direction}&granularity=${granularity}`,
  );
}

export function getHallOfShame(
  limit = 20,
  granularity: Granularity = "week",
): Promise<RankingsOut> {
  return apiFetch<RankingsOut>(
    `/observatoire/hall-of-shame?limit=${limit}&granularity=${granularity}`,
  );
}

export function getInflationMap(
  granularity: Granularity = "week",
): Promise<MapOut> {
  return apiFetch<MapOut>(`/observatoire/map?granularity=${granularity}`);
}
