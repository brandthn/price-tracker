"""Recupere des jeux de tickets publics, pour avoir de quoi valider pour de vrai.

On n'avait qu'une poignee de photos francaises, ce qui est bien trop peu et bien trop
homogene pour croire une metrique. Ce script telecharge des datasets publics et les
reecrit au format de label canonique, pour que les scripts d'eval les notent sans rien
changer.

Le choix des sources est dicte par une contrainte betement pratique : le pseudo-labelling
via Groq est plafonne par le quota gratuit. Donc on privilegie les datasets qui livrent
DEJA le texte transcrit (CORD, TrainingDataPro, WildReceipt) : un adaptateur, zero appel
LLM. SRD ne fournit que des images, donc lui demande un passage par pseudo_label.py.

Attention aux licences : TrainingDataPro est en CC-BY-NC-ND, donc usage academique non
commercial uniquement.

    python scripts/fetch_validation_data.py --datasets cord,trainingdatapro,wildreceipt
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
        review[fname] = {"reviewed": True}  # verite terrain fournie par le dataset
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
            if not ticket.produits:  # cible inexploitable
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

    # On remonte des ids de tags BIO vers les noms d'entites.
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
    """TrainingDataPro : une vingtaine de vrais tickets US, deja transcrits.

    Peu de tickets, mais le TEXTE est donne boite par boite, pas seulement les boites. Donc
    aucun pseudo-labelling. On telecharge les fichiers bruts directement, parce que le script
    de chargement du dataset est casse.

    Licence CC-BY-NC-ND : usage academique non commercial uniquement.
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
    """ExpressExpense SRD : 200 tickets anglais, mais des IMAGES SEULES.

    Aucune verite terrain. On ne lance PAS le pseudo-labelling ici : ca taperait l'API Groq,
    et il n'y a aucune raison que ca parte tout seul a chaque re-telechargement. Il faut
    appeler pseudo_label.py puis review_labels.py explicitement.
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
    print("       pas de labels : passer par pseudo_label.py puis review_labels.py")
    return n


def fetch_wildreceipt(out_root: Path, limit: int | None) -> int:
    """WildReceipt : de vrais tickets, avec leur texte transcrit et la classe de chaque champ.

    C'est ce qui a permis de passer le millier de tickets sans depenser un seul appel Groq :
    le texte est deja la, il n'y a qu'a mapper les classes vers le Ticket canonique.
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
            if fname in labels:  # collision de nom de fichier dans l'arbre imbrique (rare)
                continue
            labels[fname] = ticket
            splits[bucket].append(fname)
            total += 1
            n += 1
            if cap is not None and n >= cap:
                break
            if limit is not None and total >= limit:
                break

    _ingest("test.txt", "test", None)                 # le test de WildReceipt devient notre test
    if limit is None or total < limit:
        _ingest("train.txt", "val", 300)              # on taille une tranche de val dans le train
    if limit is None or total < limit:
        _ingest("train.txt", "train", None)           # le reste part en train

    _write_labels(out_root / "labels" / name, labels, splits)
    print(f"  WildReceipt: {len(splits['train'])} train / {len(splits['val'])} val / "
          f"{len(splits['test'])} test = {total} receipts (real text, no Groq)")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", default="cord",
                        help="liste separee par des virgules : cord,sroie,trainingdatapro,srd_images,wildreceipt")
    parser.add_argument("--limit", type=int, default=None, help="plafonne le nombre de tickets par dataset")
    parser.add_argument("--out", default=str(DEV_OCR / "data"), help="racine de sortie")
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
        except Exception as exc:  # un souci reseau sur une source ne doit pas tuer les autres
            print(f"  {key.upper()}: FAILED — {type(exc).__name__}: {exc}")
            summary[key] = 0

    print("\nRecupere :", {k: v for k, v in summary.items()})
    if summary.get("srd_images"):
        print("SRD n'a pas de labels : il faut le passer dans pseudo_label.py.")


if __name__ == "__main__":
    main()
