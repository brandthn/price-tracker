import { apiFetch } from "./client";
import type { BasketSummary, RecommendationsOut } from "./types";

export function getMyBasket(): Promise<BasketSummary> {
  return apiFetch<BasketSummary>("/me/basket", { authenticated: true });
}

export type { BasketSummary };

export function getMyRecommendations(): Promise<RecommendationsOut> {
  return apiFetch<RecommendationsOut>("/me/recommendations", {
    authenticated: true,
  });
}

export type { RecommendationsOut };