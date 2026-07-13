"""Télécharge les datasets listés dans data/raw/ocr_testing/datasets_to_use_for_testing.txt.

Le fichier source est un bout de texte libre, pas un format : on en extrait au regex
les datasets HuggingFace, les slugs Kaggle et les URL directes, pour rester tolérant
aux commentaires et au code autour.

Chaque dataset atterrit dans data/raw/<source>/<slug>/, et on saute ce qui est déjà
là : le script est rejouable.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import urlretrieve

LOGGER = logging.getLogger("download_datasets")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIST = REPO_ROOT / "data" / "raw" / "ocr_testing" / "datasets_to_use_for_testing.txt"
DEFAULT_TARGET = REPO_ROOT / "data" / "raw"

_HF_URI = re.compile(r"hf://datasets/([\w.\-]+/[\w.\-]+)")
_HF_LOAD = re.compile(r"load_dataset\(\s*[\"']([\w.\-]+/[\w.\-]+)[\"']")
_KAGGLE = re.compile(r"kagglehub\.dataset_download\(\s*[\"']([\w.\-]+/[\w.\-]+)[\"']")
_HTTP_URL = re.compile(r"https?://[^\s\"'<>]+")


def parse_dataset_file(path: Path) -> dict[str, set[str]]:
    """Rend un mapping source -> identifiants, extrait du fichier de liste.

    ``source`` is one of ``"huggingface"``, ``"kaggle"`` or ``"http"``.
    Missing files yield an empty mapping (the caller can decide whether
    to error out).
    """
    if not path.is_file():
        LOGGER.warning("Dataset list not found: %s", path)
        return {}

    text = path.read_text(encoding="utf-8", errors="replace")
    found: dict[str, set[str]] = {"huggingface": set(), "kaggle": set(), "http": set()}

    for slug in _HF_URI.findall(text):
        found["huggingface"].add(slug)
    for slug in _HF_LOAD.findall(text):
        found["huggingface"].add(slug)
    for slug in _KAGGLE.findall(text):
        found["kaggle"].add(slug)
    for url in _HTTP_URL.findall(text):
        # Skip HF URIs we already captured above.
        if url.startswith("hf://"):
            continue
        found["http"].add(url)

    return found


def _target_dir(source: str, slug_or_url: str, target_root: Path) -> Path:
    """Dossier local déterministe pour une référence de dataset."""
    if source == "http":
        parsed = urlparse(slug_or_url)
        safe = Path(parsed.netloc) / Path(parsed.path).name
        return target_root / source / safe
    safe_slug = slug_or_url.replace("/", "__")
    return target_root / source / safe_slug


def _is_already_downloaded(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _download_huggingface(slug: str, target: Path) -> None:
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required to download HuggingFace datasets. "
            "Install it with `pip install huggingface_hub`."
        ) from exc

    target.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Downloading HuggingFace dataset %s into %s", slug, target)
    snapshot_download(
        repo_id=slug,
        repo_type="dataset",
        local_dir=str(target),
        local_dir_use_symlinks=False,
    )


def _download_kaggle(slug: str, target: Path) -> None:
    try:
        import kagglehub  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "kagglehub is required to download Kaggle datasets. "
            "Install it with `pip install kagglehub`."
        ) from exc

    LOGGER.info("Downloading Kaggle dataset %s", slug)
    cache_path = Path(kagglehub.dataset_download(slug))

    target.mkdir(parents=True, exist_ok=True)
    # Un marqueur, pour que le run suivant sache que c'est déjà récupéré,
    # and a pointer to the actual cache location (kagglehub manages
    # its own cache and we don't want to duplicate gigabytes of data).
    (target / "KAGGLEHUB_PATH.txt").write_text(str(cache_path), encoding="utf-8")
    LOGGER.info("Kaggle dataset cached at %s (pointer written to %s)", cache_path, target)


def _download_http(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Downloading %s into %s", url, target)
    urlretrieve(url, target)


def download_all(
    found: dict[str, set[str]],
    target_root: Path,
    *,
    force: bool = False,
) -> list[Path]:
    """Télécharge tout ce qui a été trouvé, et rend les chemins cibles."""
    written: list[Path] = []

    for slug in sorted(found.get("huggingface", set())):
        target = _target_dir("huggingface", slug, target_root)
        if not force and _is_already_downloaded(target):
            LOGGER.info("Skipping %s (already present in %s)", slug, target)
            continue
        try:
            _download_huggingface(slug, target)
            written.append(target)
        except Exception as exc:
            LOGGER.error("Failed to download HuggingFace dataset %s: %s", slug, exc)

    for slug in sorted(found.get("kaggle", set())):
        target = _target_dir("kaggle", slug, target_root)
        if not force and _is_already_downloaded(target):
            LOGGER.info("Skipping %s (already present in %s)", slug, target)
            continue
        try:
            _download_kaggle(slug, target)
            written.append(target)
        except Exception as exc:
            LOGGER.error("Failed to download Kaggle dataset %s: %s", slug, exc)

    for url in sorted(found.get("http", set())):
        target = _target_dir("http", url, target_root)
        if not force and target.exists() and target.stat().st_size > 0:
            LOGGER.info("Skipping %s (already present in %s)", url, target)
            continue
        try:
            _download_http(url, target)
            written.append(target)
        except Exception as exc:
            LOGGER.error("Failed to download %s: %s", url, exc)

    return written


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-list",
        type=Path,
        default=DEFAULT_LIST,
        help=f"Path to the dataset list (default: {DEFAULT_LIST}).",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help=f"Where to put downloaded datasets (default: {DEFAULT_TARGET}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Retélécharge même si le dataset semble déjà là.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Logs verbeux.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    found = parse_dataset_file(args.source_list)
    if not any(found.values()):
        LOGGER.warning("No dataset references found in %s", args.source_list)
        return 0

    written = download_all(found, args.target, force=args.force)
    LOGGER.info("Done. %d dataset target(s) written.", len(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
