"use client";

// Contexte d'authentification Firebase (client).
//
// Rôle :
//  - exposer l'utilisateur courant + helpers (signIn / signUp / signOut / reset).
//  - synchroniser l'ID token dans un cookie `pt_id_token` à chaque changement
//    (`onIdTokenChanged` : login, logout, refresh auto ~1h). Ce cookie permet
//    aux Server Components (pages tickets, home) de forwarder le Bearer au
//    backend FastAPI — sans firebase-admin ni credential côté frontend.
//
// Compromis sécurité assumé (projet étudiant / démo) : le cookie n'est PAS
// httpOnly (il doit être lisible/écrivable côté client pour suivre les refresh
// du SDK web). Exposition XSS limitée par la TTL courte du token (1h) et le fait
// que le backend reste l'unique source de vérité (vérif JWT). Durcissement
// possible plus tard : session cookie httpOnly via une route handler + WIF.

import {
  createUserWithEmailAndPassword,
  onIdTokenChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signOut as fbSignOut,
  updateProfile,
  type User,
} from "firebase/auth";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { firebaseAuth, isFirebaseConfigured } from "./config";

export const ID_TOKEN_COOKIE = "pt_id_token";

function setTokenCookie(token: string) {
  const secure = typeof window !== "undefined" && window.location.protocol === "https:";
  // max-age = 1h (TTL d'un ID token Firebase). onIdTokenChanged le rafraîchira.
  document.cookie = `${ID_TOKEN_COOKIE}=${token}; Path=/; Max-Age=3600; SameSite=Lax${
    secure ? "; Secure" : ""
  }`;
}

function clearTokenCookie() {
  document.cookie = `${ID_TOKEN_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  configured: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName?: string) => Promise<void>;
  signOut: () => Promise<void>;
  sendPasswordReset: (email: string) => Promise<void>;
  getIdToken: () => Promise<string | null>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isFirebaseConfigured || !firebaseAuth) {
      setLoading(false);
      return;
    }
    const unsub = onIdTokenChanged(firebaseAuth, async (fbUser) => {
      if (fbUser) {
        const token = await fbUser.getIdToken();
        setTokenCookie(token);
      } else {
        clearTokenCookie();
      }
      setUser(fbUser);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    // Garde : appelé seulement quand l'UI a vérifié `configured`. Lève une erreur
    // explicite si jamais une action auth est tentée sans config Firebase.
    const requireAuth = () => {
      if (!firebaseAuth) {
        throw new Error("Firebase non configuré (NEXT_PUBLIC_FIREBASE_* absents).");
      }
      return firebaseAuth;
    };

    return {
      user,
      loading,
      configured: isFirebaseConfigured,
      signIn: async (email, password) => {
        await signInWithEmailAndPassword(requireAuth(), email, password);
      },
      signUp: async (email, password, displayName) => {
        const cred = await createUserWithEmailAndPassword(
          requireAuth(),
          email,
          password,
        );
        if (displayName) {
          await updateProfile(cred.user, { displayName });
        }
      },
      signOut: async () => {
        await fbSignOut(requireAuth());
        clearTokenCookie();
      },
      sendPasswordReset: async (email) => {
        await sendPasswordResetEmail(requireAuth(), email);
      },
      getIdToken: async () => {
        const current = firebaseAuth?.currentUser;
        if (!current) return null;
        return current.getIdToken();
      },
    };
  }, [user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth doit être utilisé dans <AuthProvider>");
  }
  return ctx;
}

// Traduit les codes d'erreur Firebase en messages FR pour l'UI.
export function authErrorMessage(err: unknown): string {
  const code = (err as { code?: string })?.code ?? "";
  switch (code) {
    case "auth/invalid-email":
      return "Adresse e-mail invalide.";
    case "auth/user-disabled":
      return "Ce compte a été désactivé.";
    case "auth/user-not-found":
    case "auth/wrong-password":
    case "auth/invalid-credential":
      return "E-mail ou mot de passe incorrect.";
    case "auth/email-already-in-use":
      return "Un compte existe déjà avec cet e-mail.";
    case "auth/weak-password":
      return "Mot de passe trop faible (6 caractères minimum).";
    case "auth/too-many-requests":
      return "Trop de tentatives. Réessayez plus tard.";
    case "auth/network-request-failed":
      return "Réseau indisponible. Vérifiez votre connexion.";
    default:
      return "Une erreur est survenue. Réessayez.";
  }
}
