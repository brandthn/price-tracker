
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from .config import get_settings
from .gcs import download_parquet, group_by_ticket
from .llm import download_image, filter_reliable_matches, match_ticket
from .logging import get_logger
from .pg import (
    ensure_schema,
    get_processed_ids,
    mark_processed,
    upsert_matches,
    upsert_receipt,
    get_conn,
)

logger = get_logger(__name__)




def process_ticket(proof_id: int, ticket: dict, settings) -> dict:
    enseigne = ticket.get("enseigne", "")
    produits = ticket["produits"]
    proof_file_path = ticket["proof_file_path"]

    logger.info(
        "ticket_start",
        proof_id=proof_id,
        enseigne=enseigne,
        nb_produits=len(produits),
    )


    image_bytes = download_image(proof_file_path, settings)
    if image_bytes is None:
        mark_processed(settings, proof_id, "erreur", "image_download_failed")
        return {"statut": "erreur", "raison": "image"}


    llm_result = match_ticket(
        image_bytes=image_bytes,
        proof_file_path=proof_file_path,
        produits_candidats=produits,
        enseigne=enseigne,
        settings=settings,
    )
    time.sleep(settings.prt_llm_delay_seconds)


    matches = filter_reliable_matches(
        llm_result=llm_result,
        produits_candidats=produits,
        proof_id=proof_id,
        enseigne=enseigne,
        settings=settings,
    )


    if matches:
        upsert_matches(settings, matches)

    upsert_receipt(
        settings,
        proof_id=proof_id,
        enseigne=enseigne,
        date_ticket=ticket.get("date"),
        pays=ticket.get("pays", "FR"),
        nb_produits_dataset=len(produits),
        nb_produits_matches=len(matches),
    )
    mark_processed(settings, proof_id, "ok")

    couverture = len(matches) / len(produits) if produits else 0
    logger.info(
        "ticket_done",
        proof_id=proof_id,
        matches=len(matches),
        total=len(produits),
        couverture=round(couverture, 3),
    )
    return {"statut": "ok", "nb_produits": len(produits), "nb_matches": len(matches)}




def run_analyse(settings) -> None:
    with get_conn(settings) as conn:
        with conn.cursor() as cur:

            cur.execute("SELECT COUNT(*) FROM catalogue_products")
            nb_produits = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM catalogue_labels")
            nb_labels = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*), AVG(couverture) FROM catalogue_receipts")
            row = cur.fetchone()
            nb_receipts, couv_moy = row[0], row[1] or 0

            cur.execute(
                "SELECT statut, COUNT(*) FROM catalogue_progression GROUP BY statut"
            )
            progression = dict(cur.fetchall())

            cur.execute("""
                SELECT
                    CASE
                        WHEN couverture >= 0.8 THEN '≥ 80%'
                        WHEN couverture >= 0.5 THEN '50-80%'
                        WHEN couverture >= 0.2 THEN '20-50%'
                        ELSE '< 20%'
                    END AS cat,
                    COUNT(*) AS n
                FROM catalogue_receipts
                GROUP BY 1 ORDER BY 2 DESC
            """)
            distribution = cur.fetchall()

            cur.execute("""
                SELECT enseigne, COUNT(*) AS n, AVG(couverture) AS c
                FROM catalogue_receipts
                WHERE enseigne IS NOT NULL
                GROUP BY enseigne
                ORDER BY n DESC
                LIMIT 10
            """)
            top_enseignes = cur.fetchall()

    print("\n" + "=" * 55)
    print("CATALOGUE — MÉTRIQUES")
    print("=" * 55)
    print(f"  Produits uniques   : {nb_produits:,}")
    print(f"  Labels total       : {nb_labels:,}")
    print(f"  Tickets traités    : {nb_receipts:,}")
    print(f"  Couverture moyenne : {couv_moy:.1%}")
    print(f"  Progression        : {progression}")
    print("\nDistribution couverture :")
    for cat, n in distribution:
        print(f"  {cat:<10} : {n} tickets")
    print("\nTop enseignes :")
    for enseigne, n, c in top_enseignes:
        print(f"  {str(enseigne)[:40]:<40} | {n:3} tickets | {c:.0%} couv.")
    print("=" * 55)




def run(limite: int | None = None, dry_run: bool = False) -> None:
    settings = get_settings()
    debut = datetime.now(timezone.utc)

    logger.info(
        "pipeline_start",
        mode="dry_run" if dry_run else "production",
        limite=limite,
    )


    if not dry_run:
        ensure_schema(settings)


    df = download_parquet(settings)
    tickets = group_by_ticket(df)


    if not dry_run:
        processed = get_processed_ids(settings)
        logger.info("progression_loaded", already_done=len(processed))
        tickets = {pid: t for pid, t in tickets.items() if pid not in processed}

    logger.info("tickets_to_process", count=len(tickets))

    if dry_run:
        sample = next(iter(tickets.values()), {})
        logger.info("dry_run_sample", sample=sample)
        logger.info("dry_run_done")
        return

    if limite:
        tickets = dict(list(tickets.items())[:limite])


    stats = {"ok": 0, "erreur": 0, "matches": 0, "produits": 0}

    for i, (proof_id, ticket) in enumerate(tickets.items(), 1):
        logger.info("progress", current=i, total=len(tickets))
        try:
            result = process_ticket(proof_id, ticket, settings)
            if result["statut"] == "ok":
                stats["ok"] += 1
                stats["matches"] += result["nb_matches"]
                stats["produits"] += result["nb_produits"]
            else:
                stats["erreur"] += 1
        except Exception as e:
            logger.error("ticket_unexpected_error", proof_id=proof_id, error=str(e))
            mark_processed(settings, proof_id, "erreur", str(e))
            stats["erreur"] += 1

    elapsed = (datetime.now(timezone.utc) - debut).total_seconds()
    couverture = stats["matches"] / stats["produits"] if stats["produits"] else 0

    logger.info(
        "pipeline_done",
        elapsed_min=round(elapsed / 60, 1),
        ok=stats["ok"],
        erreur=stats["erreur"],
        matches=stats["matches"],
        produits=stats["produits"],
        couverture=round(couverture, 3),
    )




def main() -> None:
    parser = argparse.ArgumentParser(description="Price Tracker — worker catalogue")
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--analyse", action="store_true")
    args = parser.parse_args()

    if args.analyse:
        run_analyse(get_settings())
    else:
        run(limite=args.limite, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
