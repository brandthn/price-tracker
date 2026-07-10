// Initialisation du Firebase Web SDK (client only).
//
// On utilise UNIQUEMENT le SDK web côté navigateur (pas de firebase-admin sur le
// frontend) : la policy org `iam.disableServiceAccountKeyCreation` interdit les
// clés JSON de SA, donc pas de session cookie via Admin SDK. Le flux est :
//   login Web SDK -> ID token (JWT) -> envoyé au backend FastAPI qui le vérifie.
//
// Les `NEXT_PUBLIC_FIREBASE_*` sont des valeurs PUBLIQUES (cf. doc Firebase) :
// l'apiKey web n'est pas un secret, la sécurité repose sur les règles backend +
// le domaine autorisé dans la console Firebase. Elles sont inlinées dans le
// bundle JS au moment du `next build` (cf. Dockerfile / cloudbuild.yaml).

import { getApp, getApps, initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.authDomain && firebaseConfig.projectId,
);

// On n'initialise Firebase QUE si la config est présente : sinon `getAuth()`
// lève `auth/invalid-api-key` au chargement du module (casse le build SSR et le
// mode démo). `firebaseAuth` est donc nullable — les consommateurs doivent
// vérifier `isFirebaseConfigured` avant de l'utiliser.
let firebaseApp: FirebaseApp | null = null;
let firebaseAuth: Auth | null = null;

if (isFirebaseConfigured) {
  // Idempotent : évite la double-init au HMR / multiples imports.
  firebaseApp = getApps().length ? getApp() : initializeApp(firebaseConfig);
  firebaseAuth = getAuth(firebaseApp);
}

export { firebaseApp, firebaseAuth };
