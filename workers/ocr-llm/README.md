# worker-ocr-llm — OCR tier-2 (LLM Groq)

Second worker OCR **indépendant**, déclenché par la boucle de feedback : quand un
utilisateur juge la première lecture erronée (👎), le backend publie le `ticket_id`
sur le topic Pub/Sub `ocr-retry`, qui pousse vers le `POST /push` de ce worker.

Contrat identique au worker OCR tier-1 (`workers/ocr`) : « on me donne un ticket,
je fais l'OCR, that's it ». Les deux workers sont indépendants ; seule diffère
l'implémentation OCR.

Pipeline `/push` :
1. Reçoit le message Pub/Sub `{"ticket_id": "..."}`.
2. Claim idempotent : `tickets.status` `ocr_done` → `ocr_processing`.
3. Lit `gcs_path` + l'extraction précédente (`prix_extraits`) en base.
4. Télécharge l'image GCS, appelle **Groq** (LLM vision) avec un **prompt
   correctif** incluant l'extraction précédente jugée erronée.
5. Réécrit `prix_extraits` (clean slate), `status='ocr_done'`, `ocr_attempts += 1`,
   `ocr_model` renseigné.

Modèle configurable via `PRT_OCR_MODEL` (défaut : même modèle que le tier-1 pour
la fiabilité ; à pointer vers un modèle plus performant ensuite).

Vision cible : tier-1 = modèle maison (VLM / Tesseract), tier-2 = LLM Groq. Pour
l'instant les deux passes sont des LLM Groq.
