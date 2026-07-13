# worker-ocr-llm — OCR tier-2 (Gemini / Vertex AI)

Le worker OCR de seconde passe, déclenché par la boucle de feedback : quand
l'utilisateur juge la première lecture erronée (👎), le backend publie le
`ticket_id` sur le topic Pub/Sub `ocr-retry`, qui pousse vers le `POST /push`
d'ici.

Même contrat que le tier-1 (`workers/ocr`) : on reçoit un ticket, on refait
l'OCR. Les deux workers sont indépendants, seule l'implémentation OCR change.

Pipeline `/push` :
1. Message Pub/Sub `{"ticket_id": "..."}`.
2. Lecture en base du `gcs_path` et de l'extraction précédente (`prix_extraits`).
3. Téléchargement de l'image, puis appel Gemini avec un prompt correctif qui
   contient l'extraction précédente — celle que l'utilisateur a rejetée.
4. Résolution EAN via `product_aliases`, comme le tier-1.
5. Réécriture de `prix_extraits` + `ocr_attempts += 1`, en une seule transaction
   (cf. `pg.persist_tier2_result`).

Pas de claim ni de machine à états : c'est le backend le gatekeeper (il ne
publie que si `ocr_attempts < max`), et une double livraison Pub/Sub ne fait que
réécrire le même résultat.

Auth Vertex via ADC — pas de clé JSON (org policy
`iam.disableServiceAccountKeyCreation`). Le SA Cloud Run doit avoir
`roles/aiplatform.user`.

| Var | Défaut | Rôle |
| --- | --- | --- |
| `PRT_OCR_MODEL` | `gemini-2.5-flash` | Modèle Gemini de la seconde passe. |
| `PRT_OCR_ENGINE_LABEL` | `gemini` | Ce qu'on écrit dans `tickets.ocr_engine`. |
| `PRT_VERTEX_LOCATION` | `global` | Endpoint Vertex (`global` couvre 2.5-flash). |
| `PRT_OCR_MAX_IMAGE_MB` | `10` | Plafond de taille d'image. |

Déploiement : bumper `worker_ocr_llm_image_tag` dans
`infra/envs/prod/variables.tf`, puis `terraform apply`.
