"""Mapping des lignes Hugging Face « open-prices » vers le format attendu par `shared.cleaner`.

Le dataset HF expose `date` et `location_osm_address_country` alors que le cleaner
attend `price_date` et `location_osm_address_country_code` (ISO alpha-2).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

_COUNTRY_NAME_TO_ISO2 = {
    "FRANCE": "FR",
    "MONACO": "MC",
    "SWITZERLAND": "CH",
    "SUISSE": "CH",
    "BELGIUM": "BE",
    "BELGIQUE": "BE",
    "LUXEMBOURG": "LU",
    "GERMANY": "DE",
    "ALLEMAGNE": "DE",
    "SPAIN": "ES",
    "ESPAGNE": "ES",
    "ITALY": "IT",
    "ITALIE": "IT",
    "UNITED KINGDOM": "GB",
    "ROYAUME-UNI": "GB",
    "GUADELOUPE": "GP",
    "MARTINIQUE": "MQ",
    "GUYANE": "GF",
    "RÉUNION": "RE",
    "REUNION": "RE",
    "MAYOTTE": "YT",
    "SAINT-MARTIN": "MF",
    "SAINT BARTHÉLEMY": "BL",
    "SAINT-BARTHÉLEMY": "BL",
    "SAINT PIERRE AND MIQUELON": "PM",
    "WALLIS AND FUTUNA": "WF",
    "NEW CALEDONIA": "NC",
    "NOUVELLE-CALÉDONIE": "NC",
    "FRENCH POLYNESIA": "PF",
    "POLYNÉSIE FRANÇAISE": "PF",
}


def _infer_country_code(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    if len(upper) == 3 and upper.isalpha():
        # Alpha-3 courants (France)
        if upper == "FRA":
            return "FR"
        if upper == "CHE":
            return "CH"
        if upper == "BEL":
            return "BE"
        if upper == "DEU":
            return "DE"
        if upper == "ESP":
            return "ES"
        if upper == "ITA":
            return "IT"
        if upper == "GBR":
            return "GB"
    normalized = re.sub(r"\s+", " ", upper)
    return _COUNTRY_NAME_TO_ISO2.get(normalized)


def hf_open_prices_row_to_cleaner_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """Construit un dict compatible avec `clean_price_record` à partir d'une ligne HF."""
    out: Dict[str, Any] = dict(row)

    if "price_date" not in out or out.get("price_date") in (None, ""):
        if "date" in out:
            out["price_date"] = out.get("date")

    country_code = out.get("location_osm_address_country_code")
    if not country_code:
        inferred = _infer_country_code(out.get("location_osm_address_country"))
        if inferred:
            out["location_osm_address_country_code"] = inferred

    if not out.get("location_name") and out.get("location_osm_display_name"):
        out["location_name"] = out.get("location_osm_display_name")

    return out
