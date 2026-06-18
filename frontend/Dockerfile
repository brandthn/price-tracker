# syntax=docker/dockerfile:1.7
# Image Next.js 16 standalone pour Cloud Run.
# Pattern recommandé Vercel : multi-stage deps → builder → runner mince.
#
# Build context attendu : RACINE du monorepo (cf. cloudbuild.yaml).
# Soumettre depuis le repo root :
#   gcloud builds submit . --config=frontend/cloudbuild.yaml \
#     --substitutions=_SHORT_SHA=$(git rev-parse --short HEAD),_API_BASE_URL=https://prt-prod-backend-y5iagyfila-ew.a.run.app \
#     --project=price-tracker-prod-01

# --- 1) deps : install node_modules à part pour cache hit max --------------
FROM node:20-bookworm-slim AS deps
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund


# --- 2) builder : npx next build (standalone) ------------------------------
FROM node:20-bookworm-slim AS builder
WORKDIR /app

# IMPORTANT : NEXT_PUBLIC_* est inline dans le JS bundle à `next build`.
# On le passe en ARG (forwardé par cloudbuild via --build-arg) et on l'expose
# en ENV pour que next build le voit.
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_DEMO_BEARER="demo"
# Firebase Auth (config web PUBLIQUE — pas un secret). Inlinée au build.
ARG NEXT_PUBLIC_FIREBASE_API_KEY=""
ARG NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=""
ARG NEXT_PUBLIC_FIREBASE_PROJECT_ID=""
ARG NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=""
ARG NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=""
ARG NEXT_PUBLIC_FIREBASE_APP_ID=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_DEMO_BEARER=$NEXT_PUBLIC_DEMO_BEARER \
    NEXT_PUBLIC_FIREBASE_API_KEY=$NEXT_PUBLIC_FIREBASE_API_KEY \
    NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=$NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN \
    NEXT_PUBLIC_FIREBASE_PROJECT_ID=$NEXT_PUBLIC_FIREBASE_PROJECT_ID \
    NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=$NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET \
    NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=$NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID \
    NEXT_PUBLIC_FIREBASE_APP_ID=$NEXT_PUBLIC_FIREBASE_APP_ID \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./

RUN npm run build


# --- 3) runner : node 20 slim + standalone bundle ---------------------------
FROM node:20-bookworm-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0

RUN groupadd -r nextjs -g 1001 && useradd -r -u 1001 -g nextjs nextjs

# `output: 'standalone'` produit .next/standalone (server.js + node_modules
# minimal) et .next/static à copier à part (cf. doc Next.js).
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

EXPOSE 8080
CMD ["node", "server.js"]
