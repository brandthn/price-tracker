#!/usr/bin/env python3
"""Append a changelog chunk to documentation.md (repo root)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOC = ROOT / "documentation.md"


def append_to_documentation(
    content: str,
    *,
    doc_path: Path | None = None,
    ensure_trailing_newline: bool = True,
) -> Path:
    """Append ``content`` to the end of ``documentation.md``.

    Parameters
    ----------
    content:
        Markdown text to append. A leading newline is added automatically
        when the file is non-empty and ``content`` does not start with ``\\n``.
    doc_path:
        Target file (default: ``<repo>/documentation.md``).
    ensure_trailing_newline:
        If True, ensure the file ends with a single newline after append.

    Returns
    -------
    Path
        Path to the documentation file that was updated.
    """
    target = doc_path or DEFAULT_DOC
    if not target.is_file():
        raise FileNotFoundError(f"Documentation file not found: {target}")

    chunk = content
    if not chunk:
        raise ValueError("content is empty; nothing to append.")

    existing = target.read_text(encoding="utf-8")
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not chunk.startswith("\n"):
        chunk = "\n" + chunk
    if ensure_trailing_newline and not chunk.endswith("\n"):
        chunk += "\n"

    target.write_text(existing + chunk, encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append a markdown chunk to documentation.md.",
    )
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        help="Read chunk from this file (UTF-8).",
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=DEFAULT_DOC,
        help=f"Documentation path (default: {DEFAULT_DOC})",
    )
    parser.add_argument(
        "text",
        nargs="?",
        help="Chunk as inline argument (ignored if --file or stdin is used).",
    )
    args = parser.parse_args()

    if args.file:
        chunk = args.file.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        chunk = sys.stdin.read()
    elif args.text:
        chunk = args.text
    else:
        parser.error("Provide --file, pipe stdin, or pass text as an argument.")

    path = append_to_documentation(chunk, doc_path=args.doc)
    print(f"Appended {len(chunk)} characters to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
