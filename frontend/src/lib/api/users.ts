import { apiFetch } from "./client";
import type { BasketSummary, RecommendationsOut } from "./types";

// Panier réel de l'utilisateur (vue « Mon budget »), agrégé côté backend
// depuis ses tickets Cloud SQL.
export function getMyBasket(): Promise<BasketSummary> {
  return apiFetch<BasketSummary>("/me/basket", { authenticated: true });
}

export type { BasketSummary };

// Substituts moins chers pour les produits récurrents du panier.
export function getMyRecommendations(): Promise<RecommendationsOut> {
  return apiFetch<RecommendationsOut>("/me/recommendations", {
    authenticated: true,
  });
}

export type { RecommendationsOut };