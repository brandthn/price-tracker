"""Parsing logic — converts raw OCR text into the structured receipt dict.

The parser is deliberately backend-agnostic: it takes a plain string and
returns the dict described in ``project_guidelines.md``. All heuristics
specific to French *tickets de caisse* live here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from receipt_ocr.backends.base import OcrBackend
from receipt_ocr.constants import (
    OUTPUT_DATE_FORMAT,
    ProductField,
    TicketField,
)
from receipt_ocr.exceptions import OcrBackendError, ReceiptParseError

logger = logging.getLogger(__name__)


# --- Regex helpers ---------------------------------------------------------

_PRICE = r"\d{1,4}[.,]\d{2}"
"""A number with two decimals, comma or dot separator (`12,34` or `12.34`)."""

# Common French date formats found on receipts.
_DATE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(\d{2})[/\-.](\d{2})[/\-.](\d{4})\s+(\d{1,2})[:hH](\d{2})"),
        "{2}{1}{0} {3:0>2}:{4}",
    ),
    (
        re.compile(r"(\d{2})[/\-.](\d{2})[/\-.](\d{2})\s+(\d{1,2})[:hH](\d{2})"),
        "20{2}{1}{0} {3:0>2}:{4}",
    ),
    (
        re.compile(r"(\d{4})[/\-.](\d{2})[/\-.](\d{2})\s+(\d{1,2})[:hH](\d{2})"),
        "{0}{1}{2} {3:0>2}:{4}",
    ),
    # Date-only fallback (no time on the line) — assume 00:00
    (
        re.compile(r"(\d{2})[/\-.](\d{2})[/\-.](\d{4})\b"),
        "{2}{1}{0} 00:00",
    ),
)

# Quantity-style lines: "3 x 1,29", "2 X 0.99", "3x1,29"
_QUANTITY_LINE = re.compile(
    rf"^\s*(?P<qty>\d{{1,3}})\s*[xX×]\s*(?P<unit_price>{_PRICE})\s*$"
)

# Weight-style lines: "0,452 kg x 5,98 €/kg" or "0.452kg X 5,98€/kg"
_WEIGHT_LINE = re.compile(
    rf"(?P<weight>\d+[.,]\d+)\s*kg\s*[xX×]?\s*(?P<unit_price>{_PRICE})\s*(?:€/?kg)?",
    re.IGNORECASE,
)
_KG_ONLY_LINE = re.compile(rf"^(?P<weight>\d+[.,]\d+)\s*kg\s*(?:€|EUR)?\s*$", re.IGNORECASE)
_PRICE_PER_KG_LINE = re.compile(
    rf"^(?P<price>{_PRICE})\s*(?:€|EUR)?\s*/?\s*kg\s*$",
    re.IGNORECASE,
)

# A typical product line ends with a price, possibly followed by € and a TVA letter.
# Examples:
#   "PAIN COMPLET           1,20 €"
#   "COCA COLA 1.5L          2,49"
#   "BANANES               2,15 A"
_PRODUCT_LINE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<price>{_PRICE})\s*(?:€|EUR)?\s*[A-Z0-9]?\s*$"
)

# Multi-line layouts (common on real photos): name on one line, price on the next.
#   "TORSADES COMPLETES U BIO 500G"
#   "1,10 €"
#   "2,20 € 11"   ← line total (optional)
#   "2 x"
_STANDALONE_PRICE = re.compile(
    rf"^(?P<price>{_PRICE})\s*(?:€|EUR)?\s*(?:\d+)?\s*$"
)
_STANDALONE_QTY = re.compile(r"^\s*(?P<qty>\d{1,3})\s*[xX×]\s*$")
_STANDALONE_QTY_COMPACT = re.compile(r"^\s*(?P<qty>\d{1,3})[xX×]\s*$")
_SECTION_HEADER = re.compile(r"^>{1,2}\s+")
_DATE_ONLY = re.compile(r"^(\d{2})[/\-.](\d{2})[/\-.](\d{2,4})$")
_TIME_ONLY = re.compile(r"^(\d{1,2}):(\d{2})$")

# Lines that should never be treated as products. Matched case-insensitively
# against the *stripped* line. Keep this conservative.
_IGNORED_KEYWORDS: tuple[str, ...] = (
    "total",
    "sous-total",
    "sous total",
    "sstotal",
    "tva",
    "t.v.a",
    "ht",
    "ttc",
    "net a payer",
    "net à payer",
    "a payer",
    "à payer",
    "montant",
    "espece",
    "espèce",
    "especes",
    "espèces",
    "carte bancaire",
    "cb ",
    "cheque",
    "chèque",
    "rendu",
    "monnaie",
    "remise",
    "fidelite",
    "fidélité",
    "points",
    "client",
    "merci",
    "au revoir",
    "siret",
    "tel ",
    "tél ",
    "rcs",
    "ape ",
    "naf ",
    "ticket",
    "caisse",
    "vendeur",
    "operateur",
    "opérateur",
    "code",
    "facture",
    "n°",
    "article(s)",
    "articles",
    "heure",
    "telephone",
    "téléphone",
    "fruits",
    "poisson",
    "chocolat",
    "dietetique",
    "diététique",
)

# Hints for chain detection — *not* a hardcoded list of brands, but
# generic French words appearing on supermarket headers we want to skip
# when looking at body text. The chain itself is inferred dynamically
# from the first non-noise line of the header.
_HEADER_NOISE = re.compile(
    r"^(www\.|http|@|tel\b|tél\b|fax\b|siret|siren|rcs|tva\s*intracom)",
    re.IGNORECASE,
)


# --- Internal data carriers ------------------------------------------------

@dataclass
class _ParsedProduct:
    """Internal representation of a product before it is serialised."""

    name: str
    unit_price: float
    units: int = 1

    def to_dict(self) -> dict:
        return {
            ProductField.NOM.value: self.name,
            ProductField.PRIX.value: round(self.unit_price, 2),
            ProductField.UNITES.value: self.units,
        }


# --- Public class ----------------------------------------------------------

class ReceiptParser:
    """Turn raw OCR text into the structured receipt dict.

    The parser owns an :class:`OcrBackend` instance (Strategy pattern),
    so the same parsing logic works regardless of which OCR engine
    produced the text. The backend can be swapped at construction time
    without touching any of the parsing code.
    """

    HEADER_LINE_COUNT = 6
    """Number of leading lines inspected to find the chain + address."""

    def __init__(self, backend: OcrBackend) -> None:
        if not isinstance(backend, OcrBackend):
            raise TypeError(
                f"backend must be an OcrBackend instance, got {type(backend).__name__}"
            )
        self._backend = backend

    # -- Top-level API ------------------------------------------------------

    def parse(self, image_path: str) -> dict:
        """Run OCR on ``image_path`` and return the structured dict."""
        try:
            text = self._backend.extract_text(image_path)
        except OcrBackendError:
            raise
        except FileNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OcrBackendError(
                f"Unexpected error while running OCR on {image_path!r}: {exc}"
            ) from exc

        return self.parse_text(text)

    def parse_text(self, text: str) -> dict:
        """Parse already-OCR'd ``text`` (useful for testing without a backend)."""
        if not text or not text.strip():
            raise ReceiptParseError("OCR returned an empty string.")

        lines = self._clean_lines(text)
        if not lines:
            raise ReceiptParseError("OCR text contained no usable lines.")

        chain, address, header_indices = self._extract_header(lines)
        date = self._extract_date(lines)
        products = self._extract_products(lines, header_skip=header_indices)

        return {
            TicketField.TICKET.value: {
                TicketField.DATE.value: date,
                TicketField.CHAINE.value: chain,
                TicketField.ADRESSE.value: address,
                TicketField.PRODUITS.value: [p.to_dict() for p in products],
            }
        }

    # -- Header (chain + address) ------------------------------------------

    def _extract_header(
        self, lines: list[str]
    ) -> tuple[str, str, set[int]]:
        """Infer the supermarket chain and address from the first few lines.

        We *never* match against a hardcoded list of brands. Instead:

        * The chain is the first non-noise, mostly-alphabetical header line.
        * The address is built from subsequent header lines that look like
          a street / postal-code line, until we hit something resembling
          a date, a price or a known body keyword.

        Returns the chain, the joined address, and the set of indices
        that were classified as header (so the product extractor knows
        to skip them).
        """
        header = lines[: self.HEADER_LINE_COUNT]

        chain = ""
        address_parts: list[str] = []
        consumed: set[int] = set()

        for idx, line in enumerate(header):
            stripped = line.strip()
            if not stripped:
                continue
            if _HEADER_NOISE.match(stripped):
                consumed.add(idx)
                continue
            if self._looks_like_date(stripped):
                consumed.add(idx)
                break
            if re.search(_PRICE, stripped):
                # We've hit the body — stop looking for header info.
                break

            if not chain and self._looks_like_chain(stripped):
                chain = stripped
                consumed.add(idx)
                continue

            if chain and self._looks_like_address(stripped):
                address_parts.append(stripped)
                consumed.add(idx)

        address = ", ".join(address_parts)
        return chain, address, consumed

    @staticmethod
    def _looks_like_chain(line: str) -> bool:
        """Heuristic: chain name is short-ish and mostly letters."""
        letters = sum(c.isalpha() for c in line)
        return letters >= 3 and letters / max(len(line), 1) >= 0.5

    @staticmethod
    def _looks_like_address(line: str) -> bool:
        """Heuristic: address lines contain a postcode or a street keyword."""
        if re.search(r"\b\d{5}\b", line):
            return True
        return bool(
            re.search(
                r"\b(rue|avenue|av\.?|bd|boulevard|chemin|place|route|rte|impasse|allée|allee|zone|zac|zi)\b",
                line,
                re.IGNORECASE,
            )
        )

    # -- Date --------------------------------------------------------------

    def _extract_date(self, lines: Iterable[str]) -> str:
        """Find the first parsable date and return it as ``yyyyMMdd HH:mm``."""
        line_list = list(lines)

        for line in line_list:
            for pattern, template in _DATE_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                try:
                    candidate = template.format(*match.groups())
                    parsed = datetime.strptime(candidate, OUTPUT_DATE_FORMAT)
                    return parsed.strftime(OUTPUT_DATE_FORMAT)
                except (ValueError, IndexError):
                    continue

        # Receipts often print date and time on separate lines (e.g. 15/10/24 then 12:40).
        date_match = None
        time_match = None
        for line in line_list:
            stripped = line.strip()
            dm = _DATE_ONLY.match(stripped)
            if dm:
                date_match = dm
            tm = _TIME_ONLY.match(stripped)
            if tm:
                time_match = tm
        if date_match and time_match:
            day, month, year = date_match.groups()
            if len(year) == 2:
                year = f"20{year}"
            hour, minute = time_match.groups()
            candidate = f"{year}{month}{day} {int(hour):02d}:{minute}"
            try:
                parsed = datetime.strptime(candidate, OUTPUT_DATE_FORMAT)
                return parsed.strftime(OUTPUT_DATE_FORMAT)
            except ValueError:
                pass
        return ""

    @staticmethod
    def _looks_like_date(line: str) -> bool:
        return any(p.search(line) for p, _ in _DATE_PATTERNS)

    # -- Products ----------------------------------------------------------

    def _extract_products(
        self, lines: list[str], header_skip: set[int] | None = None
    ) -> list[_ParsedProduct]:
        """Walk through the body lines and assemble :class:`_ParsedProduct`s.

        We use a small state machine: a product line is captured, then if
        the *next* line looks like a quantity (``3 x 1,29``) or weight
        (``0,452 kg x 5,98``) we update the previous product accordingly.

        ``header_skip`` is the set of line indices already classified as
        header (chain / address / SIRET / phone / date). They are never
        considered as products.
        """
        products: list[_ParsedProduct] = []
        seen_first_product = False
        header_skip = header_skip or set()
        pending_name: str | None = None

        def _flush_pending(
            name: str,
            unit_price: float,
            units: int = 1,
        ) -> None:
            nonlocal seen_first_product
            if name and self._is_plausible_product_name(name):
                products.append(
                    _ParsedProduct(name=name, unit_price=unit_price, units=units)
                )
                seen_first_product = True

        i = 0
        while i < len(lines):
            if i in header_skip:
                i += 1
                continue

            stripped = lines[i].strip()

            if not stripped:
                i += 1
                continue

            if _SECTION_HEADER.match(stripped):
                pending_name = None
                i += 1
                continue

            if self._looks_like_date(stripped) and not _PRODUCT_LINE.match(stripped):
                i += 1
                continue

            if self._is_ignored(stripped):
                if seen_first_product and self._is_footer_terminator(stripped):
                    break
                pending_name = None
                i += 1
                continue

            # Weight line (per-kg) on its own or embedded.
            weight_match = _WEIGHT_LINE.search(stripped)
            if weight_match and pending_name:
                unit_price = _parse_price(weight_match.group("unit_price"))
                _flush_pending(pending_name, unit_price, units=1)
                pending_name = None
                i += 1
                continue

            # Multi-line weight: "0,972 kg" then "2,79 €/kg" then "2,71 €"
            if pending_name and _KG_ONLY_LINE.match(stripped):
                per_kg = None
                if i + 1 < len(lines):
                    per_kg_m = _PRICE_PER_KG_LINE.match(lines[i + 1].strip())
                    if per_kg_m:
                        per_kg = _parse_price(per_kg_m.group("price"))
                        i += 1
                if per_kg is not None:
                    _flush_pending(pending_name, per_kg, units=1)
                    pending_name = None
                    i += 1
                    continue

            # Standalone quantity: "2 x" or "4x"
            qty_only = _STANDALONE_QTY.match(stripped) or _STANDALONE_QTY_COMPACT.match(
                stripped
            )
            if qty_only and products:
                products[-1].units = int(qty_only.group("qty"))
                pending_name = None
                i += 1
                continue

            # Standalone unit price after a product name on the previous line.
            price_only = _STANDALONE_PRICE.match(stripped)
            if price_only and pending_name:
                unit_price = _parse_price(price_only.group("price"))
                units = 1
                # Look ahead: line total then "N x", or just "N x".
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    total_m = _STANDALONE_PRICE.match(nxt)
                    if total_m and i + 2 < len(lines):
                        total_price = _parse_price(total_m.group("price"))
                        if unit_price > 0:
                            units = max(1, round(total_price / unit_price))
                        qty_m = _STANDALONE_QTY.match(
                            lines[i + 2].strip()
                        ) or _STANDALONE_QTY_COMPACT.match(lines[i + 2].strip())
                        if qty_m:
                            units = int(qty_m.group("qty"))
                        i += 2
                    else:
                        qty_m = _STANDALONE_QTY.match(nxt) or _STANDALONE_QTY_COMPACT.match(
                            nxt
                        )
                        if qty_m:
                            units = int(qty_m.group("qty"))
                            i += 1
                        elif total_m and unit_price > 0:
                            units = max(
                                1, round(_parse_price(total_m.group("price")) / unit_price)
                            )
                            i += 1
                _flush_pending(pending_name, unit_price, units=units)
                pending_name = None
                i += 1
                continue

            qty_match = _QUANTITY_LINE.match(stripped)
            product_match = _PRODUCT_LINE.match(stripped)
            if product_match and not qty_match:
                name = product_match.group("name").strip(" .-:")
                price = _parse_price(product_match.group("price"))
                product = _ParsedProduct(name=name, unit_price=price, units=1)
                if i + 1 < len(lines):
                    nxt = lines[i + 1].strip()
                    nxt_qty = _QUANTITY_LINE.match(nxt)
                    nxt_weight = _WEIGHT_LINE.search(nxt)
                    if nxt_qty:
                        product.units = int(nxt_qty.group("qty"))
                        product.unit_price = _parse_price(nxt_qty.group("unit_price"))
                        i += 1
                    elif nxt_weight:
                        product.unit_price = _parse_price(nxt_weight.group("unit_price"))
                        i += 1
                _flush_pending(product.name, product.unit_price, units=product.units)
                pending_name = None
                i += 1
                continue

            # Candidate product name (no price on this line).
            if self._is_plausible_product_name(stripped) and not _STANDALONE_PRICE.match(
                stripped
            ):
                pending_name = stripped
            else:
                pending_name = None

            i += 1

        return products

    @staticmethod
    def _is_ignored(line: str) -> bool:
        lowered = line.lower()
        return any(kw in lowered for kw in _IGNORED_KEYWORDS)

    @staticmethod
    def _is_footer_terminator(line: str) -> bool:
        """Strong signal that the product block is over (total / payment)."""
        lowered = line.lower()
        return any(
            kw in lowered
            for kw in (
                "total",
                "net a payer",
                "net à payer",
                "a payer",
                "à payer",
                "ttc",
                "carte bancaire",
                "espece",
                "espèce",
            )
        )

    @staticmethod
    def _is_plausible_product_name(name: str) -> bool:
        """Reject names that are clearly not products (mostly digits, too short)."""
        if len(name) < 2:
            return False
        if _PRICE_PER_KG_LINE.match(name) or _STANDALONE_PRICE.match(name):
            return False
        letters = sum(c.isalpha() for c in name)
        return letters >= 2

    # -- Lines preprocessing -----------------------------------------------

    @staticmethod
    def _clean_lines(text: str) -> list[str]:
        """Normalise whitespace, drop empty lines, keep order."""
        cleaned: list[str] = []
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            # Collapse repeated whitespace inside the line.
            stripped = re.sub(r"\s+", " ", stripped)
            cleaned.append(stripped)
        return cleaned


# --- Helpers ---------------------------------------------------------------

def _parse_price(token: str) -> float:
    """Convert ``"12,34"`` or ``"12.34"`` to ``12.34``."""
    return float(token.replace(",", "."))
