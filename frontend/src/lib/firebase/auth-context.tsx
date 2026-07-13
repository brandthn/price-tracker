"use client";

// onIdTokenChanged sync le token dans pt_id_token, les RSC lisent ce cookie
// cookie pas httpOnly (le sdk web doit pouvoir l'écrire au refresh) - ok vu
// la TTL 1h + verif JWT backend

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
  // 1h = TTL du id token
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
