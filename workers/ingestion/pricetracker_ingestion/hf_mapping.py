
from __future__ import annotations

import re
from typing import Any


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

    out = dict(row)

    if out.get("price_date") in (None, ""):
        if "date" in out:
            out["price_date"] = out.get("date")

    if not out.get("location_osm_address_country_code"):
        inferred = _infer_country_code(out.get("location_osm_address_country"))
        if inferred:
            out["location_osm_address_country_code"] = inferred


    if not out.get("location_name") and out.get("location_osm_display_name"):
        out["location_name"] = out.get("location_osm_display_name")

    return out
