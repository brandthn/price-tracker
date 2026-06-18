"use client";

import { useAuth } from "@/lib/firebase/auth-context";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function UserInfo() {
  const { user, configured, signOut } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  // En mode démo (Firebase non configuré) rien à afficher.
  if (!configured || !user) return null;

  const label = user.displayName || user.email || "Compte";
  const initial = (user.email ?? "?").charAt(0).toUpperCase();

  async function onLogout() {
    await signOut();
    router.replace("/login");
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full p-1 pr-3 transition hover:bg-gray-2 dark:hover:bg-dark-3"
      >
        <span className="flex size-9 items-center justify-center rounded-full bg-primary text-sm font-semibold text-white">
          {initial}
        </span>
        <span className="hidden max-w-[12rem] truncate text-sm font-medium text-dark sm:block dark:text-white">
          {label}
        </span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-50 mt-2 w-56 rounded-lg border border-stroke bg-white p-2 shadow-2 dark:border-dark-3 dark:bg-gray-dark">
            <div className="border-b border-stroke px-3 py-2 dark:border-dark-3">
              <p className="truncate text-sm font-medium text-dark dark:text-white">
                {user.displayName || "Utilisateur"}
              </p>
              <p className="truncate text-xs text-dark-6">{user.email}</p>
            </div>
            <button
              onClick={onLogout}
              className="mt-1 w-full rounded-md px-3 py-2 text-left text-sm font-medium text-red transition hover:bg-red-light-6 dark:hover:bg-red/10"
            >
              Se déconnecter
            </button>
          </div>
        </>
      )}
    </div>
  );
}
