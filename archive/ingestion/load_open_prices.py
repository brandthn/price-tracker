
import os
from pathlib import Path
from loguru import logger          # logs lisibles et datés
from datasets import load_dataset  # librairie officielle HuggingFace
import duckdb                      # pour vérifier ce qu'on vient de charger
from dotenv import load_dotenv

# Charge les variables du fichier .env (chemin des données, etc.)
load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
# On lit le chemin depuis .env, avec une valeur par défaut si absent
RAW_PATH = Path(os.getenv("RAW_DATA_PATH", "./raw"))
OUTPUT_FILE = RAW_PATH / "open_prices" / "open_prices.parquet"

# Colonnes qu'on garde : seulement ce dont on a besoin
# (le dataset complet a 48 colonnes — inutile de tout garder)
COLUMNS_A_GARDER = [
    "id",
    "product_code",          # code-barres du produit
    "category_tag",          # catégorie (pour les produits frais sans code-barre)
    "price",                 # prix observé
    "price_is_discounted",   # est-ce un prix promotionnel ?
    "price_without_discount",# prix original avant promo
    "price_per",             # unité : KILOGRAM ou UNIT
    "currency",              # EUR, CHF, USD...
    "location_id",           # identifiant du magasin
    "date",                  # date de relevé du prix
    "proof_type",            # RECEIPT, PRICE_TAG... (source de la preuve)
    "location_osm_display_name",    # nom complet du magasin
    "location_osm_address_city",    # ville
    "location_osm_address_postcode",# code postal
    "location_osm_address_country", # pays
    "location_osm_lat",             # latitude GPS
    "location_osm_lon",             # longitude GPS
    "source",                # application qui a soumis le prix
]


def telecharger_open_prices() -> None:
    """
    Étape 1 : Téléchargement depuis HuggingFace
    Étape 2 : Sauvegarde en Parquet local
    Étape 3 : Vérification rapide du résultat
    """

    # Crée le dossier de destination s'il n'existe pas encore
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Connexion à HuggingFace pour télécharger Open Prices...")

    # load_dataset() télécharge automatiquement le fichier Parquet
    # split="prices" = le seul split disponible dans ce dataset
    # columns= = on ne charge que les colonnes utiles (économise RAM et disque)
    dataset = load_dataset(
        "openfoodfacts/open-prices",
        split="prices",
        columns=COLUMNS_A_GARDER,
    )

    nombre_lignes = len(dataset)
    logger.info(f"Dataset reçu : {nombre_lignes:,} lignes, {len(COLUMNS_A_GARDER)} colonnes")

    # Conversion en Parquet : format binaire compressé, parfait pour DuckDB
    # Beaucoup plus rapide et léger qu'un CSV équivalent
    logger.info(f"Sauvegarde vers {OUTPUT_FILE}...")
    dataset.to_parquet(str(OUTPUT_FILE))

    # ─── Vérification : on lit ce qu'on vient d'écrire ───────────────────────
    # Si le fichier est corrompu ou vide, on le détecte ici
    con = duckdb.connect()
    resultat = con.execute(
        f"SELECT COUNT(*) AS nb_lignes FROM read_parquet('{OUTPUT_FILE}')"
    ).fetchone()

    logger.success(
        f"Fichier vérifié : {resultat[0]:,} lignes dans {OUTPUT_FILE}"
    )
    con.close()


if __name__ == "__main__":
    telecharger_open_prices()