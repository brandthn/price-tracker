"""
FICHIER : ingestion/load_insee.py
RÔLE    : Récupérer les indices d'inflation officiels de l'INSEE
          via leur API publique et les stocker en CSV.

POURQUOI CE FICHIER ?
    Le projet compare l'inflation réelle (Open Prices) avec
    l'inflation officielle (INSEE). Ce script va chercher
    l'Indice des Prix à la Consommation (IPC) mensuel.

API utilisée : https://api.insee.fr/series/BDM/V1
Série utilisée : 001759970 = IPC général France
"""

import os
import csv
from pathlib import Path
from datetime import datetime
import httpx                   # client HTTP asynchrone, plus moderne que requests
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

RAW_PATH = Path(os.getenv("RAW_DATA_PATH", "./raw"))
OUTPUT_FILE = RAW_PATH / "insee" / "ipc_france.csv"

# Identifiant de la série INSEE : IPC tous produits, France entière
SERIE_INSEE = "001759970"

# On veut les données depuis 2020 pour voir l'évolution sur 5 ans
DATE_DEBUT = "2020-01"


def fetch_ipc_insee() -> list[dict]:
    """
    Appelle l'API INSEE et retourne une liste de points
    sous la forme : [{"date": "2024-01", "valeur": 120.3}, ...]

    L'API INSEE renvoie du JSON avec une structure imbriquée,
    on extrait uniquement ce qui nous intéresse.
    """
    url = (
        f"https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/{SERIE_INSEE}"
        f"?startPeriod={DATE_DEBUT}&format=json"
    )

    headers = {
        "Authorization": f"Bearer {os.getenv('INSEE_API_KEY', '')}",
        "Accept": "application/json",
    }

    logger.info(f"Appel API INSEE : série {SERIE_INSEE} depuis {DATE_DEBUT}...")

    # httpx.get() envoie la requête HTTP et attend la réponse
    # timeout=30 : si l'INSEE ne répond pas en 30s, on abandonne proprement
    response = httpx.get(url, headers=headers, timeout=30)

    # Vérifie que la réponse est correcte (code 200)
    # Lève une exception si l'API renvoie une erreur
    response.raise_for_status()

    donnees_brutes = response.json()

    # Navigation dans la structure JSON de l'INSEE
    # (structure : DataSet > Series > Obs)
    observations = (
        donnees_brutes
        .get("DataSet", {})
        .get("Series", {})
        .get("Obs", [])
    )

    # On transforme chaque observation en dictionnaire simple
    resultats = [
        {
            "date": obs.get("@TIME_PERIOD"),    # ex: "2024-01"
            "valeur_ipc": float(obs.get("@OBS_VALUE", 0)),
        }
        for obs in observations
        if obs.get("@OBS_VALUE")  # on ignore les périodes sans valeur
    ]

    logger.info(f"{len(resultats)} observations récupérées")
    return resultats


def sauvegarder_csv(donnees: list[dict]) -> None:
    """Écrit la liste de données dans un fichier CSV."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "valeur_ipc"])
        writer.writeheader()
        writer.writerows(donnees)

    logger.success(f"INSEE IPC sauvegardé : {OUTPUT_FILE} ({len(donnees)} lignes)")


if __name__ == "__main__":
    donnees = fetch_ipc_insee()
    sauvegarder_csv(donnees)