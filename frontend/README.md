# frontend — PriceTracker

Interface utilisateur Next.js 16 déployée sur Cloud Run.

Deux espaces : **l'Observatoire** (public, pas de compte) et **Mon budget** (personnel, nécessite un compte Firebase).

## Lancer en local

```bash
npm install
cp .env.example .env.local
npm run dev
```

`.env.local` attend les variables Firebase publiques (`NEXT_PUBLIC_FIREBASE_*`) et l'URL du backend (`NEXT_PUBLIC_API_URL`). Les valeurs de prod sont dans la config Cloud Run — demander à quelqu'un de l'équipe.

## Variables d'environnement

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_API_URL` | URL du backend FastAPI |
| `NEXT_PUBLIC_FIREBASE_API_KEY` | Config Firebase (clé publique) |
| `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` | — |
| `NEXT_PUBLIC_FIREBASE_PROJECT_ID` | — |

## Build et déploiement

```bash
# Build local
npm run build

# Déployer (via Cloud Build)
gcloud builds submit --config cloudbuild.yaml
# puis bumper frontend_image_tag dans infra/envs/prod/cloud_run.tf → terraform apply
```

## Tests

```bash
npm run lint
npm run type-check
```
