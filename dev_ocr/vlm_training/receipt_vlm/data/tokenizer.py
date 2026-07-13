"""Tokenizer caractere pour la cible du decodeur.

Vocabulaire : les tokens speciaux, les marqueurs de champ du schema linearise, et les
caracteres. Le caractere garde un vocabulaire vraiment ouvert (n'importe quel nom de
produit, n'importe quel accent, aucun mot hors vocabulaire), et les marqueurs restent
des tokens uniques pour que la structure du schema soit un symbole chacun.

Un BPE pourrait le remplacer plus tard sans toucher au modele : meme interface
encode/decode.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from receipt_vlm.data.lin_schema import FIELD_TOKENS

PAD, BOS, EOS, UNK = "[PAD]", "[BOS]", "[EOS]", "[UNK]"
_SPECIALS = (PAD, BOS, EOS, UNK)

# Le jeu de caracteres par defaut, quand on ne construit pas depuis un corpus :
# common Latin-1/Extended-A letters with diacritics, so real receipts rarely hit [UNK].
_DEFAULT_CHARS = (
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz{|}~"
    "€£$¥"
    "àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ"
    "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝ"
    "ăąćčđęğłńœřśşšțťůźżžıİ"
)


class CharTokenizer:
    """Tokenizer reversible. Les ids vont dans l'ordre : speciaux, marqueurs, caracteres."""

    def __init__(self, chars: Iterable[str]) -> None:
        # On dedoublonne, en gardant ce qui n'est pas deja un special ou un marqueur.
        seen: list[str] = []
        for ch in chars:
            if ch and ch not in seen:
                seen.append(ch)
        self.itos: list[str] = list(_SPECIALS) + list(FIELD_TOKENS) + seen
        self.stoi: dict[str, int] = {tok: i for i, tok in enumerate(self.itos)}
        self.pad_id = self.stoi[PAD]
        self.bos_id = self.stoi[BOS]
        self.eos_id = self.stoi[EOS]
        self.unk_id = self.stoi[UNK]
        self._markers = sorted(FIELD_TOKENS, key=len, reverse=True)  # longest-match first

    @property
    def vocab_size(self) -> int:
        return len(self.itos)

    def encode(self, text: str, add_special: bool = True) -> list[int]:
        ids: list[int] = [self.bos_id] if add_special else []
        i, n = 0, len(text)
        while i < n:
            for marker in self._markers:  # atomic field tokens
                if text.startswith(marker, i):
                    ids.append(self.stoi[marker])
                    i += len(marker)
                    break
            else:
                ids.append(self.stoi.get(text[i], self.unk_id))
                i += 1
        if add_special:
            ids.append(self.eos_id)
        return ids

    def decode(self, ids: Iterable[int], skip_special: bool = True) -> str:
        skip = {self.pad_id, self.bos_id, self.eos_id} if skip_special else set()
        out: list[str] = []
        for i in ids:
            if i in skip:
                continue
            out.append(self.itos[i] if 0 <= i < len(self.itos) else "")
        return "".join(out)

    @classmethod
    def from_corpus(cls, texts: Iterable[str], extra: str = "") -> "CharTokenizer":
        """Construit le vocabulaire depuis les caracteres reellement presents."""
        chars: list[str] = []
        seen: set[str] = set()
        for text in texts:
            i, n = 0, len(text)
            while i < n:
                for marker in FIELD_TOKENS:
                    if text.startswith(marker, i):
                        i += len(marker)
                        break
                else:
                    ch = text[i]
                    if ch not in seen:
                        seen.add(ch)
                        chars.append(ch)
                    i += 1
        for ch in extra:
            if ch not in seen:
                seen.add(ch)
                chars.append(ch)
        return cls(chars)

    @classmethod
    def default(cls) -> "CharTokenizer":
        return cls(_DEFAULT_CHARS)

    def save(self, path: str | Path) -> None:
        chars = self.itos[len(_SPECIALS) + len(FIELD_TOKENS):]
        Path(path).write_text(
            json.dumps({"chars": chars}, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "CharTokenizer":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["chars"])
