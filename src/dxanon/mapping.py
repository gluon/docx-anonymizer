"""The correspondence table: real value on one side, pseudonym on the other.

This is the sensitive object of the whole exercise. It holds exactly what
is meant to be protected, so it exists in memory for the length of one
round trip and is never written anywhere. There is deliberately no way to
save it: a `save` method sitting here would be an invitation to call it,
and one call puts the client's names on the firm's disk, outliving the
work that needed them.

The cost is stated rather than hidden: close the window mid-cycle and the
real names are gone, which the window says before it happens.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SCHEMA = 1


@dataclass(frozen=True)
class Entry:
    real: str
    pseudonym: str
    kind: str = "name"  # name | org | id | author | email | phone
    note: str = ""


class Mapping:
    def __init__(self, entries: list[Entry] | None = None, used: set[str] | None = None) -> None:
        self.entries: list[Entry] = list(entries or [])
        #: Real values that a substitution pass actually consumed. Empty
        #: means "not recorded yet", not "none": a table loaded from an
        #: older file has no record, and must not have its entries treated
        #: as unused. See :meth:`was_used`.
        self.used: set[str] = set(used or ())

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

    def mark_used(self, reals: set[str]) -> None:
        self.used |= {r for r in reals if r}

    def was_used(self, entry: Entry) -> bool:
        """True when the entry fired, or when nothing was recorded.

        Defaulting to True keeps the return-trip check strict for tables
        written before this was recorded: it may ask about a pseudonym
        that never appeared, which is a visible, correctable nuisance,
        where the opposite silently accepts a half-restored document.
        """
        return not self.used or entry.real in self.used

    def conflicts(self) -> list[str]:
        """Table entries that cannot coexist, in plain words.

        Two shapes break a round trip, and both are easy to create by hand:

        * a pseudonym that contains another entry's real value, so the
          masked text still shows something the table says to hide and the
          refusal check fires on a value that was never the client's;
        * a pseudonym that is also another entry's real value, so restoring
          cannot tell which one was meant.

        Caught when the table is built rather than at export, where the
        symptom is confusing and the cause is three screens away.
        """
        problems: list[str] = []
        reals = {e.real for e in self.entries if e.real}
        for entry in self.entries:
            if not entry.pseudonym:
                continue
            if entry.pseudonym in reals:
                problems.append(
                    f"« {entry.pseudonym} » est à la fois un pseudonyme et une vraie valeur"
                )
                continue
            for real in reals:
                if real != entry.real and _contains(entry.pseudonym, real):
                    problems.append(
                        f"le pseudonyme « {entry.pseudonym} » contient « {real} », "
                        "qui doit être masqué"
                    )
                    break
        return problems

    def collides_with(self, text: str) -> list[Entry]:
        """Pseudonyms that already occur in the source text.

        A pseudonym that is also a word of the document cannot be undone
        reliably: restoring it would rewrite text that was never masked.
        """
        return [e for e in self.entries if e.pseudonym and e.pseudonym in text]


def _contains(pseudonym: str, real: str) -> bool:
    """Whether a pseudonym really shows a value that must be masked.

    Word by word, and deliberately the same rule as the export check in
    :func:`dxanon.engine.scan`. When the two disagreed, the table warned
    about "Orion Industries" holding "Industrie" and the export refused
    on the same grounds, both of them on a word that was not a name.
    """
    pattern = re.escape(real)
    if real[:1].isalnum():
        pattern = r"\b" + pattern
    if real[-1:].isalnum():
        pattern = pattern + r"\b"
    return re.search(pattern, pseudonym) is not None


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


#: Pools for generated pseudonyms. Deliberately ordinary French names, so
#: the masked text still reads like a legal document and the AI reasons on
#: prose rather than on tokens such as [[PERS_01]]. Kept away from the very
#: most frequent surnames, which are likely to be in the document already.
#: Kept apart by grammatical gender so a pseudonym can follow the civility
#: that precedes the real name. "Monsieur Claire FORESTIER" is not a leak,
#: but it tells the reader the text has been through a machine, and a
#: reader who stops trusting the text stops reasoning about it.
FIRST_NAMES_M = (
    "Marc", "Olivier", "Damien", "Vincent", "Fabrice", "Gilles", "Bruno",
    "Serge", "Hugo", "Patrick", "Thibaut", "Romain", "Xavier", "Yann",
)
FIRST_NAMES_F = (
    "Claire", "Hélène", "Sabine", "Nadia", "Aurore", "Léa", "Margaux",
    "Camille", "Inès", "Agnès", "Delphine", "Maud", "Elsa", "Clarisse",
)
FIRST_NAMES = FIRST_NAMES_M + FIRST_NAMES_F

#: Invented place names, so a town does not come back as a surname.
PLACE_NAMES = (
    "Valmont", "Beauvoir", "Fontenoy", "Rochefort-sur-Brède", "Saint-Avre",
    "Cléry", "Montbrison-le-Haut", "Verneuil", "Aubrac-les-Bains", "Sénan",
    "Chambeuil", "Pradines", "Villeneuve-d'Arce", "Lormont-le-Vieux",
)
SURNAMES = (
    "Lemoine", "Rivière", "Delacroix", "Vautrin", "Marsac", "Chevalier",
    "Aubert", "Forestier", "Lagarde", "Vasseur", "Montal", "Berthier",
    "Esnault", "Grandjean", "Vanel", "Dupleix", "Soler", "Mercier",
    "Nivelle", "Ferrand",
)
#: Invented initialisms, so a bank or an agency stays an initialism.
#: Checked against no real organisation on purpose: these are meant to be
#: obviously not a real name to anyone who knows the field.
ACRONYMS = (
    "KVT", "ZRM", "QBX", "VNK", "XPF", "JHD", "WQL", "YTB", "FKZ", "PGV",
)

COMPANY_NAMES = (
    "Orion", "Altaïr", "Vega", "Mistral", "Calypso", "Hélios", "Boréal",
    "Zephyr", "Cassiopée", "Lyra", "Pollux", "Arcturus",
)


def propose(kind: str, taken: set[str], text: str = "") -> str:
    """A pseudonym that collides with neither the table nor the document.

    A name that already occurs in the source cannot be used: restoring it
    would rewrite text that was never masked. So the document itself is
    part of what the generator avoids, not only the table.
    """
    if kind == "org":
        candidates = list(COMPANY_NAMES)
    elif kind == "place":
        candidates = list(PLACE_NAMES)
    elif kind == "acronym":
        candidates = list(ACRONYMS)
    else:
        firsts = {"name_f": FIRST_NAMES_F, "name_m": FIRST_NAMES_M}.get(kind, FIRST_NAMES)
        # Step through both pools at once rather than nesting them, so the
        # grid does not fill with twenty people who all share a surname.
        span = max(len(firsts), len(SURNAMES))
        candidates = [
            f"{firsts[i % len(firsts)]} {SURNAMES[(i * 7) % len(SURNAMES)]}"
            for i in range(span * len(SURNAMES))
        ]

    folded_text = _strip_accents(text).casefold()
    folded_taken = {_strip_accents(t).casefold() for t in taken}

    for suffix in ("", *(f" {n}" for n in range(2, 60))):
        for candidate in candidates:
            full = f"{candidate}{suffix}"
            folded = _strip_accents(full).casefold()
            if folded in folded_taken:
                continue
            # Word by word as well as whole: a pseudonym that is a word
            # of another pseudonym can be restored as the wrong person
            # the moment a model shortens the longer one.
            if any(_strip_accents(part).casefold() in folded_taken for part in full.split()):
                continue
            # Accents and case are not a disguise: "Marc Rivière" collides
            # with "Marc Riviere" in the source, and a pseudonym that is
            # already in the document cannot be undone.
            if folded_text and any(
                _strip_accents(part).casefold() in folded_text for part in full.split()
            ):
                continue
            return full
    raise RuntimeError("no free pseudonym left, which should be impossible")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
