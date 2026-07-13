// cookie posé par l'AuthProvider, relu côté RSC et côté client
// attention: next/headers rend la route dynamique (les pages authent sont déjà force-dynamic)

const COOKIE_NAME = "pt_id_token";

async function readServerToken(): Promise<string | null> {
  // import dyn: next/headers n'existe pas côté client, le garde typeof window
  // évite qu'il finisse dans le bundle
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
