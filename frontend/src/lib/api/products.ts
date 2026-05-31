import { apiFetch } from "./client";
import type { Product, ProductSearchResult, Substitute } from "./types";

export function searchProducts(
  q: string,
  limit = 20,
): Promise<ProductSearchResult> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return apiFetch<ProductSearchResult>(`/products/search?${params}`);
}

export function getProduct(ean: string): Promise<Product> {
  return apiFetch<Product>(`/products/${encodeURIComponent(ean)}`);
}

export function getSubstitutes(ean: string, k = 5): Promise<Substitute[]> {
  return apiFetch<Substitute[]>(
    `/products/${encodeURIComponent(ean)}/substitutes?k=${k}`,
  );
}

export type { Product, Substitute };
