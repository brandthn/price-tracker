"use client";

import { authErrorMessage, useAuth } from "@/lib/firebase/auth-context";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Field, FormError, SubmitButton } from "../_components/ui";

export default function RegisterPage() {
  const { signUp, configured } = useAuth();
  const router = useRouter();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured) {
      setError("Firebase non configuré (NEXT_PUBLIC_FIREBASE_* manquants).");
      return;
    }
    if (password.length < 6) {
      setError("Mot de passe trop court (6 caractères minimum).");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      await signUp(email, password, displayName || undefined);
      // le cookie est posé par l'AuthProvider (onIdTokenChanged)
      router.replace("/");
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <FormError message={error} />
      <Field
        label="Nom (optionnel)"
        type="text"
        autoComplete="name"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
      />
      <Field
        label="E-mail"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Field
        label="Mot de passe"
        type="password"
        autoComplete="new-password"
        required
        minLength={6}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <SubmitButton loading={loading}>Créer mon compte</SubmitButton>
      <p className="text-center text-sm text-dark-6">
        Déjà un compte ?{" "}
        <Link href="/login" className="text-primary hover:underline">
          Se connecter
        </Link>
      </p>
    </form>
  );
}
