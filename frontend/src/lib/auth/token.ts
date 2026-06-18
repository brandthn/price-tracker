// Lecture isomorphe de l'ID token Firebase pour les appels backend.
//
// Le token est stocké dans le cookie `pt_id_token` par l'AuthProvider (client).
// - Server Components (RSC) : lecture via `next/headers` (cookie envoyé par le
//   navigateur sur la navigation). Rend la route dynamique — les pages
//   authentifiées sont déjà en `force-dynamic`.
// - Client Components : lecture directe de `document.cookie`.

const COOKIE_NAME = "pt_id_token";

async function readServerToken(): Promise<string | null> {
  // Import dynamique : `next/headers` n'existe que côté serveur. Le bundler ne
  // l'inclut pas dans le bundle client grâce au garde `typeof window`.
  const { cookies } = await import("next/headers");
  const store = await cookies();
  return store.get(COOKIE_NAME)?.value ?? null;
}

function readClientToken(): string | null {
  const match = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${COOKIE_NAME}=`));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : null;
}

export async function getRequestToken(): Promise<string | null> {
  if (typeof window === "undefined") {
    return readServerToken();
  }
  return readClientToken();
}
