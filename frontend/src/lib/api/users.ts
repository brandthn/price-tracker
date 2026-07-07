import { apiFetch } from "./client";
import type { BasketSummary } from "./types";

// Panier réel de l'utilisateur (vue « Mon budget »), agrégé côté backend
// depuis ses tickets Cloud SQL.
export function getMyBasket(): Promise<BasketSummary> {
  return apiFetch<BasketSummary>("/me/basket", { authenticated: true });
}

export type { BasketSummary };
