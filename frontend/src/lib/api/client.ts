// Wrapper fetch typé pour l'API backend FastAPI (Cloud Run).
// Lit `NEXT_PUBLIC_API_BASE_URL` côté serveur ET client (RSC + client components).
// Mode démo Phase 10 : Bearer accepté tel quel par le backend (`PRT_AUTH_DISABLE=1`).

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const DEMO_BEARER = process.env.NEXT_PUBLIC_DEMO_BEARER ?? "demo";

if (!API_BASE) {
  // Log au démarrage côté serveur — le frontend reste utilisable pour les pages
  // statiques mais les fetches échoueront proprement avec ApiError.
  console.warn(
    "[api] NEXT_PUBLIC_API_BASE_URL non défini — voir .env.example",
  );
}

export class ApiError extends Error {
  status: number;
  detail: string | undefined;
  constructor(status: number, detail: string | undefined, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.name = "ApiError";
  }
}

type FetchOptions = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  authenticated?: boolean;
  // Par défaut : 'no-store' (toujours frais). Override pour mettre en cache
  // les RSC (ex: catalogue produit qui change rarement).
  cache?: RequestCache;
  // ISR : `next: { revalidate: 60 }`.
  next?: { revalidate?: number; tags?: string[] };
};

export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  const {
    method = "GET",
    body,
    authenticated = false,
    cache = "no-store",
    next,
  } = options;

  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (authenticated) {
    headers["Authorization"] = `Bearer ${DEMO_BEARER}`;
  }

  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: next ? undefined : cache,
      next,
    });
  } catch (err) {
    throw new ApiError(
      0,
      undefined,
      `Réseau indisponible vers ${url} (${(err as Error).message})`,
    );
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const data = await response.json();
      detail = typeof data?.detail === "string" ? data.detail : undefined;
    } catch {
      // Pas de JSON body, on garde l'erreur HTTP brute.
    }
    throw new ApiError(
      response.status,
      detail,
      `${method} ${path} → HTTP ${response.status}${detail ? ` (${detail})` : ""}`,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function apiBaseUrl(): string {
  return API_BASE;
}
