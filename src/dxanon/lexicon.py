"""Words the user has already said are not names.

Over-detection is the right default, but a tool that asks the same
question every week is a tool people stop reading. "Cabinet", "Cachet",
"Ajout" are not names, and once that has been said it should stay said.

Deliberately one-way: only decisions to *keep* a word are remembered.
Remembering a decision to mask would be harmless; remembering a decision
not to mask is the one with a cost, so it is the one kept visible, in a
plain text file the user can open, read and empty.

Identifiers are never remembered. A decision not to mask an IBAN is
about that one IBAN, never about IBANs.
"""

from __future__ import annotations

from pathlib import Path

HEADER = """# Mots que vous avez indiqué ne pas vouloir masquer.
# Un mot par ligne. Vous pouvez éditer ou vider ce fichier à tout moment.
# Les numéros (sécurité sociale, IBAN, SIRET), adresses et dates ne sont
# jamais enregistrés ici : la décision ne vaut que pour le document où
# elle a été prise.
"""


class Lexicon:
    def __init__(self, path: Path, words: set[str] | None = None) -> None:
        self.path = Path(path)
        self.words = set(words or ())

    @classmethod
    def load(cls, path) -> "Lexicon":
        path = Path(path)
        if not path.exists():
            return cls(path)
        words = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        return cls(path, words)

    def remember(self, word: str) -> None:
        if word:
            self.words.add(word)

    def forget(self, word: str) -> None:
        self.words.discard(word)

    def knows(self, word: str) -> bool:
        return word in self.words

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(sorted(self.words))
        self.path.write_text(f"{HEADER}\n{body}\n", encoding="utf-8")
