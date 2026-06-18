"use client";

// Garde client : protège les pages de l'espace authentifié.
// - Tant que l'état Firebase charge → spinner (évite un flash de la page).
// - Si Firebase non configuré (NEXT_PUBLIC_FIREBASE_* absents) → laisse passer :
//   mode démo, le backend tourne encore en PRT_AUTH_DISABLE=1.
// - Si configuré et non connecté → redirige vers /login.

import { useAuth } from "@/lib/firebase/auth-context";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { user, loading, configured } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const mustRedirect = configured && !loading && !user;

  useEffect(() => {
    if (mustRedirect) {
      const next = encodeURIComponent(pathname ?? "/");
      router.replace(`/login?next=${next}`);
    }
  }, [mustRedirect, pathname, router]);

  if (configured && (loading || !user)) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="size-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return <>{children}</>;
}
