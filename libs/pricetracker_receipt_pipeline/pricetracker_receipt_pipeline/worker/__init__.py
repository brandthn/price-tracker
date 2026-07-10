"""Runtime commun des workers OCR par backend.

Calqué sur ``workers/ocr-llm/pricetracker_ocr_llm`` : auth OIDC, logging
structlog JSON, GCS, enveloppe Pub/Sub push, Cloud SQL (pool + persistance
atomique), mapper schéma canonique → rows DB, bootstrap des poids modèle.
"""
