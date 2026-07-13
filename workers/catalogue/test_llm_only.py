
import os
os.environ["GOOGLE_CLOUD_PROJECT"] = "price-tracker-prod-01"

import json
from pricetracker_catalogue.config import get_settings
from pricetracker_catalogue.gcs import download_parquet, group_by_ticket
from pricetracker_catalogue.llm import download_image, match_ticket, filter_reliable_matches

settings = get_settings()


df = download_parquet(settings)
tickets = group_by_ticket(df)


for i, (proof_id, ticket) in enumerate(list(tickets.items())[:10]):
    print(f"\n{'='*60}")
    print(f"Ticket {i+1}/10 — proof_id={proof_id} | {ticket['enseigne']}")
    print(f"  {len(ticket['produits'])} produits dans le dataset")

    image_bytes = download_image(ticket["proof_file_path"], settings)
    if not image_bytes:
        print("  ❌ Image non téléchargeable")
        continue

    result = match_ticket(
        image_bytes=image_bytes,
        proof_file_path=ticket["proof_file_path"],
        produits_candidats=ticket["produits"],
        enseigne=ticket["enseigne"],
        settings=settings,
    )

    matches = filter_reliable_matches(
        llm_result=result,
        produits_candidats=ticket["produits"],
        proof_id=proof_id,
        enseigne=ticket["enseigne"],
        settings=settings,
    )

    print(f"  ✅ {len(matches)} matchés / {len(ticket['produits'])} produits")
    for m in matches:
        print(f"     EAN {m['ean']} | '{m['libelle_original']}' | {m['prix']}€ | confiance ok")

    if "erreur" in result:
        print(f"  ⚠️  Erreur LLM : {result['erreur']}")