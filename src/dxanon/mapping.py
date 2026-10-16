"""The correspondence table: real value on one side, pseudonym on the other.

This file is the sensitive one.  It holds exactly what the exercise is
meant to protect, it never travels inside an exported document, and it is
written to disk rather than kept in memory so that closing the window
between the outward and the return trip does not lose the real names.

The format is deliberately a flat list of entries rather than a dict keyed
by document, so that grouping entries under a case file later (phase 2)
is a change of container, not a rewrite.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

SCHEMA = 1


@dataclass(frozen=True)
class Entry:
    real: str
    pseudonym: str
    kind: str = "name"  # name | org | id | author | email | phone
    note: str = ""


class Mapping:
    def __init__(self, entries: list[Entry] | None = None) -> None:
        self.entries: list[Entry] = list(entries or [])

    def add(self, real: str, pseudonym: str, kind: str = "name", note: str = "") -> Entry:
        if not real:
            raise ValueError("a mapping entry needs a real value")
        existing = self.for_real(real)
        if existing is not None:
            return existing
        entry = Entry(real=real, pseudonym=pseudonym, kind=kind, note=note)
        self.entries.append(entry)
        return entry

    def for_real(self, real: str) -> Entry | None:
        return next((e for e in self.entries if e.real == real), None)

    def for_pseudonym(self, pseudonym: str) -> Entry | None:
        return next((e for e in self.entries if e.pseudonym == pseudonym), None)

    def forward(self) -> list[tuple[str, str]]:
        """Real to pseudonym, longest first so a full name wins over a surname."""
        return _ordered((e.real, e.pseudonym) for e in self.entries)

    def backward(self) -> list[tuple[str, str]]:
        return _ordered((e.pseudonym, e.real) for e in self.entries)

    def collides_with(self, text: str) -> list[Entry]:
        """Pseudonyms that already occur in the source text.

        A pseudonym that is also a word of the document cannot be undone
        reliably: restoring it would rewrite text that was never masked.
        """
        return [e for e in self.entries if e.pseudonym and e.pseudonym in text]

    def save(self, path) -> None:
        payload = {"schema": SCHEMA, "entries": [asdict(e) for e in self.entries]}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Mapping":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA:
            raise ValueError(f"unsupported mapping schema: {payload.get('schema')!r}")
        return cls([Entry(**row) for row in payload["entries"]])


def _ordered(pairs) -> list[tuple[str, str]]:
    # Longest source first: replacing "Jean Dupont" before "Dupont" keeps the
    # two from fighting over the same characters.
    return sorted((p for p in pairs if p[0]), key=lambda p: (-len(p[0]), p[0]))


def variants(name: str) -> list[str]:
    """Spellings of one name that a document is likely to use.

    Mechanical, not clever: case forms, civility prefixes, initial plus
    surname, and the unaccented spelling.  Everything here is generated
    from what the user declared, never guessed from the document.
    """
    name = name.strip()
    if not name:
        return []

    found: list[str] = []
    pieces = name.split()
    surname = pieces[-1]

    candidates = [name, name.upper(), name.title(), surname, surname.upper(), surname.title()]
    if len(pieces) > 1:
        first = pieces[0]
        candidates += [
            f"{first[0]}. {surname}",
            f"{first} {surname.upper()}",
            f"{first.title()} {surname.upper()}",
        ]
    for civility in ("M.", "Mme", "Monsieur", "Madame", "Maître", "Me", "Dr", "Docteur"):
        candidates.append(f"{civility} {surname}")
        candidates.append(f"{civility} {surname.upper()}")

    for candidate in candidates:
        stripped = _strip_accents(candidate)
        for value in (candidate, stripped):
            if value and value not in found:
                found.append(value)
    return found


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
