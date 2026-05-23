"""Adaptation des colonnes du dataset HF Open Prices au format attendu par `cleaner`.

Le dataset HuggingFace expose certaines colonnes sous des noms qui ne matchent pas
directement les attentes du cleaner :
- HF: `date`                              → cleaner: `price_date`
- HF: `location_osm_address_country`      → cleaner: `location_osm_address_country_code`
  (HF donne souvent le NOM du pays, le cleaner attend l'ISO alpha-2)

Cette couche est volontairement mince : si HF change un nom de colonne demain,
c'est ici qu'on patche, sans toucher au cleaner ni aux enrichissements.
"""

from __future__ import annotations

import re
from typing import Any

# Pays courants en clair dans le dataset HF → ISO alpha-2.
# Liste minimaliste : étendre au besoin. Les pays non listés produiront None,
# ce qui sera traduit en rejet INVALID_COUNTRY par le cleaner.
_COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "FRANCE": "FR",
    "MONACO": "MC",
    "GUADELOUPE": "GP",
    "MARTINIQUE": "MQ",
    "GUYANE": "GF",
    "GUYANE FRANCAISE": "GF",
    "FRENCH GUIANA": "GF",
    "REUNION": "RE",
    "LA REUNION": "RE",
    "MAYOTTE": "YT",
    "SAINT-MARTIN": "MF",
    "SAINT MARTIN": "MF",
    "SAINT-BARTHELEMY": "BL",
    "SAINT BARTHELEMY": "BL",
    "SAINT-PIERRE-ET-MIQUELON": "PM",
    "SAINT PIERRE AND MIQUELON": "PM",
    "WALLIS-ET-FUTUNA": "WF",
    "WALLIS AND FUTUNA": "WF",
    "NOUVELLE-CALEDONIE": "NC",
    "NEW CALEDONIA": "NC",
    "POLYNESIE FRANCAISE": "PF",
    "FRENCH POLYNESIA": "PF",
    "BELGIQUE": "BE",
    "BELGIUM": "BE",
    "SUISSE": "CH",
    "SWITZERLAND": "CH",
    "LUXEMBOURG": "LU",
    "ALLEMAGNE": "DE",
    "GERMANY": "DE",
    "ESPAGNE": "ES",
    "SPAIN": "ES",
    "ITALIE": "IT",
    "ITALY": "IT",
    "ROYAUME-UNI": "GB",
    "UNITED KINGDOM": "GB",
}

# Alpha-3 → Alpha-2 pour les pays susceptibles d'apparaître chez Open Prices.
_COUNTRY_ALPHA3_TO_ISO2: dict[str, str] = {
    "FRA": "FR",
    "BEL": "BE",
    "CHE": "CH",
    "DEU": "DE",
    "ESP": "ES",
    "ITA": "IT",
    "GBR": "GB",
    "MCO": "MC",
}


def _infer_country_code(value: Any) -> str | None:
    """Convertit une valeur de pays HF (ISO2, ISO3, ou nom en clair) en ISO alpha-2."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    if len(upper) == 3 and upper.isalpha() and upper in _COUNTRY_ALPHA3_TO_ISO2:
        return _COUNTRY_ALPHA3_TO_ISO2[upper]
    normalized = re.sub(r"\s+", " ", upper)
    return _COUNTRY_NAME_TO_ISO2.get(normalized)


def map_hf_row(row: dict[str, Any]) -> dict[str, Any]:
    """Réécrit une ligne HF en format consommable par le cleaner.

    Idempotent : si `price_date` est déjà présent, on ne touche pas. Si
    `location_osm_address_country_code` est déjà l'ISO2, idem.
    """
    out = dict(row)

    if out.get("price_date") in (None, ""):
        if "date" in out:
            out["price_date"] = out.get("date")

    if not out.get("location_osm_address_country_code"):
        inferred = _infer_country_code(out.get("location_osm_address_country"))
        if inferred:
            out["location_osm_address_country_code"] = inferred

    # Fallback display_name → location_name si absent (cas fréquent HF).
    if not out.get("location_name") and out.get("location_osm_display_name"):
        out["location_name"] = out.get("location_osm_display_name")

    return out
