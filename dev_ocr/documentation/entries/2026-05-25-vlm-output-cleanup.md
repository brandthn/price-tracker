## Version 0.1.4 (unreleased)

### Entry 8 — 2026-05-25 (UTC+2)

**Scope:** Harden VLM JSON post-processing and Groq smoke-test reliability after duplicate / malformed outputs on real receipts.

#### Problem observed

Running `scripts/test_groq_receipt.py` on `4PQOWWaPoa.jpg` sometimes produced:

- The same product repeated several times (e.g. `RAISIN BLANC ITALIA` ×3–4)
- Concatenated or partial JSON blobs from the model (two `{ "ticket": ... }` blocks, truncated arrays)
- Dates in French form (`15/10/24`) instead of `yyyyMMdd HH:mm`
- Fractional `unites` (e.g. `0.972` for weight sold by kg), which broke strict integer validation

The README schema was not violated in structure, but `produits` could contain duplicates and parsing could fail validation retries.

#### What was implemented

| Area | File | Change |
|------|------|--------|
| Multi-JSON parsing | `vlm_parse.py` | `_collect_json_candidates`, `_loads_json` scores payloads and keeps the richest valid `ticket` |
| Product cleanup | `vlm_parse.py` | `_dedupe_vlm_products`, `_normalize_product_name`, `_round_price`; skip non-dict product rows |
| Date coercion | `vlm_parse.py` | `_coerce_vlm_date` for `DD/MM/YY`, `DD/MM/YYYY`, with/without time |
| Units coercion | `vlm_parse.py` | Fractional floats rounded to `max(1, round(value))` |
| Groq token budget | `constants.py`, `groq_provider.py` | `DEFAULT_GROQ_MAX_TOKENS = 4096` to reduce truncated JSON |
| Prompts | `backends/vlm/prompts.py` | No duplicate lines, single JSON object, integer `unites` |
| Smoke script | `scripts/test_groq_receipt.py` | `load_project_env()`, paths resolved from repo root, `chdir(ROOT)` |
| Tests | `tests/test_vlm_parse.py` | Dedup, multi-blob JSON, date/units coercion |

#### Cleaning pipeline (after Groq / any VLM JSON mode)

```text
raw model text
  → _collect_json_candidates (fences, repeated {"ticket":, split on }\n{)
  → _try_parse_json_string (+ json_repair)
  → pick best payload by _score_vlm_payload (product count, header fields)
  → normalize_vlm_ticket
       → coerce date, normalize names, round prices, coerce units
       → _dedupe_vlm_products (exact nom + prix + unites)
  → ReceiptParser / extract_receipt output (README schema)
```

#### Duplicate rule

Two products are merged only when **all three** match after normalization:

- `nom_produit` (whitespace collapsed)
- `prix_unitaire_ou_kg` (rounded to 2 decimals)
- `unites`

Same name with different price or quantity stays as separate lines.

#### How to verify

```powershell
$env:PYTHONPATH = "src"
python scripts/test_groq_receipt.py data/raw/images_tickets_caisse/4PQOWWaPoa.jpg
pytest tests/test_vlm_parse.py --no-integration
```

Expected on `4PQOWWaPoa.jpg`: 5 unique products, no repeated raisin line, valid JSON on stdout.

#### References

- Groq provider setup: Entry 7 in this file
- Append further changelog chunks: `python scripts/add_entry_to_documentation.py --file documentation/entries/<name>.md`

---
