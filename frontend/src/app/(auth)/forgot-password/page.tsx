"use client";

import { authErrorMessage, useAuth } from "@/lib/firebase/auth-context";
import Link from "next/link";
import { useState } from "react";
import { Field, FormError, FormSuccess, SubmitButton } from "../_components/ui";

export default function ForgotPasswordPage() {
  const { sendPasswordReset, configured } = useAuth();

  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured) {
      setError("Firebase non configuré (NEXT_PUBLIC_FIREBASE_* manquants).");
      return;
    }
    setError(null);
    setSuccess(null);
    setLoading(true);
    try {
      await sendPasswordReset(email);
      setSuccess(
        "Si un compte existe pour cet e-mail, un lien de réinitialisation a été envoyé.",
      );
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <FormError message={error} />
      <FormSuccess message={success} />
      <p className="text-sm text-dark-6">
        Entrez votre e-mail pour recevoir un lien de réinitialisation.
      </p>
      <Field
        label="E-mail"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <SubmitButton loading={loading}>Envoyer le lien</SubmitButton>
      <p className="text-center text-sm text-dark-6">
        <Link href="/login" className="text-primary hover:underline">
          Retour à la connexion
        </Link>
      </p>
    </form>
  );
}
