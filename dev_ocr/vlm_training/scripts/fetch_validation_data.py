"""Fetch public Latin-script receipt datasets as real validation data.

French real receipts are scarce (~18 photos), which is too narrow to validate the
model. This pulls public, no-auth receipt datasets from the HuggingFace hub and writes
them in the canonical ``{"ticket": {...}}`` label format under ``dev_ocr/data/`` so
``scripts/evaluate.py`` can score against real receipts in more languages.

Datasets:
  - CORD-v2 (naver-clova-ix/cord-v2) — ~1k Indonesian receipts, Latin script, FULL line
    items. Strong OCR / line-item validation. Reuses receipt_vlm.data.cord_adapter.
  - SROIE 2019 (best-effort HF mirror) — English; company/date/address/total, NO line
    items. Header-field validation only. Skipped gracefully if unavailable.
  - TrainingDataPro OCR Receipts Text Detection (HF) — 20 US receipts, real
    transcribed shop/item/date_time text (not pseudo-labelled). CC-BY-NC-ND-4.0 —
    non-commercial eval use only. Reuses receipt_vlm.data.trainingdatapro_adapter.
  - ExpressExpense SRD ("srd_images") — 200 English restaurant receipts, MIT licence,
    direct public zip. IMAGES ONLY: no ground truth, so this fetcher does NOT run
    pseudo-labelling (that means live Groq calls) — see its own docstring for the
    follow-up `pseudo_label.py` + `review_labels.py` steps.

Output layout (per dataset <name>):
    dev_ocr/data/raw/<name>/<id>.jpg
    dev_ocr/data/labels/<name>/<id>.json          # {"ticket": {...}}
    dev_ocr/data/labels/<name>/splits.json        # {"val": [...], "test": [...]}
    dev_ocr/data/labels/<name>/review_status.json # all reviewed=true (dataset ground truth)

Usage:
    python scripts/fetch_validation_data.py --datasets cord,sroie,trainingdatapro,srd_images [--limit N]
    # then, e.g.:
    python scripts/evaluate.py --checkpoint <merged.pt> \
        --images ../data/raw/cord_v2 --labels ../data/labels/cord_v2 --split test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receipt_vlm.data.schema import Ticket  # noqa: E402

DEV_OCR = Path(__file__).resolve().parents[2]  # .../dev_ocr


def _write_labels(lbl_dir: Path, labels: dict[str, Ticket], splits: dict[str, list[str]]) -> None:
    lbl_dir.mkdir(parents=True, exist_ok=True)
    review: dict[str, dict] = {}
    for fname, ticket in labels.items():
        stem = Path(fname).stem
        (lbl_dir / f"{stem}.json").write_text(
            json.dumps(ticket.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        review[fname] = {"reviewed": True}  # dataset-provided ground truth
    (lbl_dir / "splits.json").write_text(
        json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (lbl_dir / "review_status.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_cord(out_root: Path, limit: int | None) -> int:
    """CORD-v2 → canonical labels. HF 'validation' -> our 'val', 'test' -> 'test'."""
    from datasets import load_dataset

    from receipt_vlm.data.cord_adapter import ticket_from_cord_ground_truth

    name = "cord_v2"
    img_dir = out_root / "raw" / name
    img_dir.mkdir(parents=True, exist_ok=True)

    def _load(split: str):
        try:
            return load_dataset("naver-clova-ix/cord-v2", split=split)
        except Exception:
            return load_dataset("naver-clova-ix/cord-v2", split=split, trust_remote_code=True)

    labels: dict[str, Ticket] = {}
    splits: dict[str, list[str]] = {"val": [], "test": []}
    total = 0
    for hf_split, our_split in (("validation", "val"), ("test", "test")):
        ds = _load(hf_split)
        ground_truths = ds["ground_truth"]
        for index, gt in enumerate(ground_truths):
            ticket = ticket_from_cord_ground_truth(gt)
            if not ticket.produits:  # unusable target
                continue
            fname = f"cord_{hf_split}_{index:04d}.jpg"
            ds[index]["image"].convert("RGB").save(img_dir / fname, "JPEG", quality=92)
            labels[fname] = ticket
            splits[our_split].append(fname)
            total += 1
            if limit is not None and total >= limit:
                break
        if limit is not None and total >= limit:
            break

    _write_labels(out_root / "labels" / name, labels, splits)
    print(f"  CORD-v2: {len(splits['val'])} val + {len(splits['test'])} test = {total} receipts")
    return total


def fetch_sroie(out_root: Path, limit: int | None) -> int:
    """Best-effort SROIE via a HF mirror with BIO entity tags. Skips if incompatible."""
    from datasets import load_dataset

    from receipt_vlm.data.sroie_adapter import ticket_from_sroie_entities

    name = "sroie"
    ds = None
    for repo in ("darentang/sroie", "Theivaprakasham/sroie"):
        try:
            ds = load_dataset(repo, split="test")
            break
        except Exception:
            continue
    if ds is None:
        print("  SROIE: skipped (no reachable HF mirror / needs manual download)")
        return 0

    cols = ds.column_names
    if not ({"words", "ner_tags"} <= set(cols)):
        print(f"  SROIE: skipped (unexpected schema {cols}); use sroie_adapter on a local copy")
        return 0

    # Map BIO tag ids -> entity name via the feature's class names.
    try:
        tag_names = ds.features["ner_tags"].feature.names
    except Exception:
        print("  SROIE: skipped (cannot read ner_tags class names)")
        return 0

    img_dir = out_root / "raw" / name
    img_dir.mkdir(parents=True, exist_ok=True)
    labels: dict[str, Ticket] = {}
    splits: dict[str, list[str]] = {"test": []}
    total = 0
    for index in range(len(ds)):
        row = ds[index]
        entities: dict[str, list[str]] = {}
        for word, tag_id in zip(row["words"], row["ner_tags"]):
            tag = tag_names[tag_id]
            if tag == "O" or "-" not in tag:
                continue
            key = tag.split("-", 1)[1].lower()  # COMPANY/DATE/ADDRESS/TOTAL
            entities.setdefault(key, []).append(str(word))
        joined = {k: " ".join(v) for k, v in entities.items()}
        ticket = ticket_from_sroie_entities(joined)
        if not ticket.chaine_supermarche and not ticket.date:
            continue
        image = row.get("image")
        if image is None:
            print("  SROIE: skipped (rows carry no image column)")
            return 0
        fname = f"sroie_test_{index:04d}.jpg"
        image.convert("RGB").save(img_dir / fname, "JPEG", quality=92)
        labels[fname] = ticket
        splits["test"].append(fname)
        total += 1
        if limit is not None and total >= limit:
            break

    _write_labels(out_root / "labels" / name, labels, splits)
    print(f"  SROIE: {total} test receipts (header fields only, no line items)")
    return total


def fetch_trainingdatapro(out_root: Path, limit: int | None) -> int:
    """TrainingDataPro OCR Receipts Text Detection (HF) -> canonical labels.

    Only 20 US receipts, but real box-level TRANSCRIBED TEXT (shop/item/date_time),
    not just boxes -- downloaded via raw file access (hf_hub_download), bypassing the
    dataset's broken/deprecated loading script. Licence: CC-BY-NC-ND-4.0 (non-commercial,
    no derivatives) -- stricter than the other sources; keep to non-commercial eval use.
    """
    import tarfile

    from huggingface_hub import hf_hub_download

    from receipt_vlm.data.trainingdatapro_adapter import load_trainingdatapro_samples

    name = "trainingdatapro"
    repo = "TrainingDataPro/ocr-receipts-text-detection"
    img_dir = out_root / "raw" / name
    img_dir.mkdir(parents=True, exist_ok=True)

    xml_path = hf_hub_download(repo, "data/annotations.xml", repo_type="dataset")
    tar_path = hf_hub_download(repo, "data/images.tar.gz", repo_type="dataset")
    Path(img_dir / "annotations.xml").write_bytes(Path(xml_path).read_bytes())
    with tarfile.open(tar_path) as tf:
        tf.extractall(img_dir)  # -> img_dir/images/*.jpg

    # Flatten images/*.jpg up to img_dir so the adapter's relative image lookup works.
    inner = img_dir / "images"
    if inner.is_dir():
        for f in inner.iterdir():
            f.rename(img_dir / f.name)
        inner.rmdir()

    samples = load_trainingdatapro_samples(img_dir, limit=limit)
    labels: dict[str, Ticket] = {}
    splits: dict[str, list[str]] = {"val": [], "test": []}
    for i, sample in enumerate(samples):
        fname = Path(sample.image).name
        labels[fname] = sample.ticket
        splits["val" if i % 2 == 0 else "test"].append(fname)

    _write_labels(out_root / "labels" / name, labels, splits)
    print(f"  TrainingDataPro: {len(splits['val'])} val + {len(splits['test'])} test "
          f"= {len(samples)} receipts (CC-BY-NC-ND-4.0, non-commercial eval only)")
    return len(samples)


def fetch_srd_images(out_root: Path, limit: int | None) -> int:
    """ExpressExpense SRD (200 English receipts, MIT) -- IMAGES ONLY, no ground truth.

    No pseudo-label step runs here (that means live Groq API calls, which shouldn't
    fire silently on every fetch re-run). After this, label them explicitly:

        python scripts/pseudo_label.py --images ../data/raw/expressexpense_srd \
            --output ../data/labels/expressexpense_srd
        python scripts/review_labels.py --list test   # then mark-reviewed
    """
    import urllib.request
    import zipfile

    name = "expressexpense_srd"
    img_dir = out_root / "raw" / name
    img_dir.mkdir(parents=True, exist_ok=True)
    if any(img_dir.glob("*.jpg")):
        print(f"  SRD: images already present in {img_dir}, skipping download")
        return len(list(img_dir.glob("*.jpg")))

    url = "https://expressexpense.com/large-receipt-image-dataset-SRD.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    zip_path = out_root / "srd_tmp.zip"
    with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as fh:
        fh.write(resp.read())
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(img_dir)
    zip_path.unlink()

    n = len(list(img_dir.glob("*.jpg")))
    if limit is not None and n > limit:
        for extra in sorted(img_dir.glob("*.jpg"))[limit:]:
            extra.unlink()
        n = limit
    print(f"  SRD: {n} images landed in {img_dir} (MIT licence)")
    print("       NOT LABELLED YET -- run scripts/pseudo_label.py on this folder, "
          "then scripts/review_labels.py.")
    return n


def fetch_wildreceipt(out_root: Path, limit: int | None) -> int:
    """WildReceipt (OpenMMLab) -> canonical labels. Real transcribed text + KIE classes.

    Direct public download (no account); ~1.7k English receipts with per-box text + field
    class, mapped straight to Ticket by receipt_vlm.data.wildreceipt_adapter (no Groq).
    Images stay in their nested image_files/ tree under raw/wildreceipt (load_real_samples
    rglobs, matching by basename). Licence: research use (SDMGR / MMOCR).
    """
    import tarfile
    import urllib.request

    from receipt_vlm.data.wildreceipt_adapter import iter_wildreceipt

    name = "wildreceipt"
    raw_dir = out_root / "raw" / name
    if not (raw_dir / "train.txt").is_file():
        raw_dir.parent.mkdir(parents=True, exist_ok=True)
        url = "https://download.openmmlab.com/mmocr/data/wildreceipt.tar"
        tar_path = out_root / "wildreceipt.tar"
        print(f"  WildReceipt: downloading {url} (~185 MB) ...", flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(tar_path, "wb") as fh:
            fh.write(resp.read())
        with tarfile.open(tar_path) as tf:
            tf.extractall(out_root / "raw")  # -> raw/wildreceipt/
        tar_path.unlink()

    labels: dict[str, Ticket] = {}
    splits: dict[str, list[str]] = {"train": [], "val": [], "test": []}
    total = 0

    def _ingest(split_file: str, bucket: str, cap: int | None) -> None:
        nonlocal total
        n = 0
        for image_path, ticket in iter_wildreceipt(raw_dir, split_file):
            fname = image_path.name
            if fname in labels:  # basename collision across the nested tree (rare)
                continue
            labels[fname] = ticket
            splits[bucket].append(fname)
            total += 1
            n += 1
            if cap is not None and n >= cap:
                break
            if limit is not None and total >= limit:
                break

    _ingest("test.txt", "test", None)                 # WildReceipt test -> our test
    if limit is None or total < limit:
        _ingest("train.txt", "val", 300)              # carve a val slice from train
    if limit is None or total < limit:
        _ingest("train.txt", "train", None)           # remainder -> train (skips val dupes)

    _write_labels(out_root / "labels" / name, labels, splits)
    print(f"  WildReceipt: {len(splits['train'])} train / {len(splits['val'])} val / "
          f"{len(splits['test'])} test = {total} receipts (real text, no Groq)")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", default="cord",
                        help="comma list: cord,sroie,trainingdatapro,srd_images,wildreceipt")
    parser.add_argument("--limit", type=int, default=None, help="cap receipts per dataset")
    parser.add_argument("--out", default=str(DEV_OCR / "data"), help="output root")
    args = parser.parse_args()

    out_root = Path(args.out)
    wanted = {d.strip().lower() for d in args.datasets.split(",") if d.strip()}
    fetchers = {
        "cord": fetch_cord,
        "sroie": fetch_sroie,
        "trainingdatapro": fetch_trainingdatapro,
        "srd_images": fetch_srd_images,
        "wildreceipt": fetch_wildreceipt,
    }

    print(f"Writing validation data under {out_root}")
    summary: dict[str, int] = {}
    for key in ("cord", "sroie", "trainingdatapro", "srd_images", "wildreceipt"):
        if key not in wanted:
            continue
        try:
            summary[key] = fetchers[key](out_root, args.limit)
        except Exception as exc:  # network/HF/version issues must not abort the rest
            print(f"  {key.upper()}: FAILED — {type(exc).__name__}: {exc}")
            summary[key] = 0

    print("\nDone. Landed:", {k: v for k, v in summary.items()})
    dir_name = {"cord": "cord_v2"}
    for key, n in summary.items():
        if not n:
            continue
        if key == "srd_images":
            print("  next: python scripts/pseudo_label.py --images ../data/raw/expressexpense_srd "
                  "--output ../data/labels/expressexpense_srd")
            continue
        name = dir_name.get(key, key)
        print(f"  eval: python scripts/evaluate.py --checkpoint <merged.pt> "
              f"--images ../data/raw/{name} --labels ../data/labels/{name} --split test")


if __name__ == "__main__":
    main()
