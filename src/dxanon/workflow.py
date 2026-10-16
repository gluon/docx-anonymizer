"""The grid: what the user is actually asked to decide, and the defaults.

Kept free of any toolkit so the decisions can be tested without a window.
The interface is a thin layer over this.

Two things matter more than the widgets:

**The default on an uncertain row is to mask.** Over-masking spoils some
prose and is noticed immediately; under-masking leaks a name and is
noticed never. The whole detection design errs that way, and the grid
has to agree with it.

**Spellings of one person get one pseudonym.** ``Jean DUPONT``,
``DUPONT`` and ``Dupont`` are three rows but one man. Giving them three
unrelated pseudonyms produces a text where he appears to be three people,
which is worse than useless to an AI asked to follow an argument.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from . import detect
from .detect import Certainty
from .mapping import Mapping, propose


class Decision(str, Enum):
    REPLACE = "replace"
    KEEP = "keep"


@dataclass
class Row:
    value: str
    certainty: Certainty
    why: str
    occurrences: int
    decision: Decision
    kind: str = "candidate"
    pseudonym: str = ""
    group: str = ""

    @property
    def is_person_like(self) -> bool:
        """Whether this row should get a name or a placeholder.

        Decided on the kind, never on the certainty. A social security
        number whose check digit fails is still a number: judging by
        certainty handed it a person's name and produced "numéro de
        sécurité sociale Altaïr" in the masked text.
        """
        return self.kind not in detect.IDENTIFIER_KINDS


@dataclass
class Grid:
    rows: list[Row] = field(default_factory=list)
    images: list[str] = field(default_factory=list)

    def to_mapping(self) -> Mapping:
        mapping = Mapping()
        for row in self.rows:
            if row.decision is Decision.REPLACE and row.pseudonym:
                mapping.add(row.value, row.pseudonym, kind=_kind_of(row))
        return mapping

    def conflicts(self) -> list[str]:
        return self.to_mapping().conflicts()

    def set_decision(self, value: str, decision: Decision) -> None:
        for row in self.rows:
            if row.value == value:
                row.decision = decision


def _kind_of(row: Row) -> str:
    return "id" if not row.is_person_like else "name"


DEFAULTS = {
    # Arithmetic says what it is; there is nothing to arbitrate.
    Certainty.CERTAIN: Decision.REPLACE,
    # A party to a cited judgment is a public name, and masking it breaks
    # the citation and the reasoning that rests on it.
    Certainty.CASE_LAW: Decision.KEEP,
    # Mask unless told otherwise: see the module docstring.
    Certainty.CONFIRM: Decision.REPLACE,
}


def build(text: str, known: list[str] | None = None, images: list[str] | None = None) -> Grid:
    """Detect, group by person, and assign one pseudonym per person."""
    rows = [
        Row(value=value, certainty=certainty, why=why, occurrences=count,
            decision=DEFAULTS[certainty], kind=kind)
        for value, certainty, why, count, kind in detect.group(detect.find(text, known=known))
    ]
    _assign(rows, text)
    return Grid(rows=rows, images=list(images or []))


def _assign(rows: list[Row], text: str) -> None:
    taken: set[str] = set()

    counters: dict[str, int] = {}
    for row in rows:
        if row.decision is Decision.KEEP:
            continue
        if not row.is_person_like:
            row.pseudonym = _mask_identifier(row.value, counters)
            taken.add(row.pseudonym)
            continue
        row.group = _person_key(row.value)

    # One base pseudonym per person, then each spelling rendered to match
    # the shape and case of the row it replaces.
    bases: dict[str, str] = {}
    for row in rows:
        if not row.group or row.decision is Decision.KEEP:
            continue
        if row.group not in bases:
            bases[row.group] = propose(_kind_from_context(row.value, text), taken, text=text)
            taken.add(bases[row.group])
        row.pseudonym = _render_like(bases[row.group], row.value)


def _person_key(value: str) -> str:
    """What makes two spellings the same person: the last word, folded.

    Crude on purpose. It joins "Jean DUPONT", "DUPONT" and "Dupont", and
    it will also join two unrelated people who share a surname, which the
    user can see and split in the grid. The opposite error, splitting one
    person into three, is invisible in the result.
    """
    words = [w for w in value.replace("'", " ").split() if w]
    return _fold(words[-1]).upper() if words else _fold(value).upper()


import re  # noqa: E402  (kept beside the context helpers it serves)

_PLACE_BEFORE = re.compile(
    r"(?:\b\d{5}\s+|\bà\s+|\bau\s+|\bBarreau\s+(?:de|d['’])\s*|\bCA\s+|\bTribunal[^.\n]{0,30}\s+de\s+)$",
    re.IGNORECASE,
)
_ORG_BEFORE = re.compile(
    r"\b(?:SAS|SASU|SARL|EURL|SA|SCI|SNC|SCOP|SCP|SELARL|GIE|soci[ée]t[ée]|Ste|St[ée]|entreprise|groupe)\s+$",
    re.IGNORECASE,
)
_FEMININE_BEFORE = re.compile(r"\b(?:Madame|Mme|Mademoiselle|Mlle)\s+$")
_MASCULINE_BEFORE = re.compile(r"\b(?:Monsieur|M\.|MM\.)\s+$")


def _kind_from_context(value: str, text: str) -> str:
    """What the surrounding words say this name is.

    Read from the text rather than guessed from the name itself, because
    a surname and a town look alike and only the context separates them.
    Every occurrence votes; the most frequent reading wins.
    """
    votes: dict[str, int] = {}
    for match in re.finditer(re.escape(value), text):
        before = text[max(0, match.start() - 60):match.start()]
        if _ORG_BEFORE.search(before):
            kind = "org"
        elif _PLACE_BEFORE.search(before):
            kind = "place"
        elif _FEMININE_BEFORE.search(before):
            kind = "name_f"
        elif _MASCULINE_BEFORE.search(before):
            kind = "name_m"
        else:
            continue
        votes[kind] = votes.get(kind, 0) + 1

    if votes:
        return max(votes.items(), key=lambda item: item[1])[0]
    return "org" if _looks_like_org(value) else "name"


def _looks_like_org(value: str) -> bool:
    return len(value.split()) > 1 and value.upper() == value


def _render_like(base: str, original: str) -> str:
    """Shape the pseudonym like the spelling it replaces.

    "Jean DUPONT" becomes "Claire FORESTIER", "DUPONT" becomes
    "FORESTIER", "Dupont" becomes "Forestier". Without this the masked
    text reads as if written by someone who cannot keep a name straight,
    and the reader stops trusting it.
    """
    parts = base.split()
    first, last = (parts[0], parts[-1]) if len(parts) > 1 else ("", parts[0])
    words = original.split()

    if len(words) >= 2 and first:
        rendered = f"{_case_like(first, words[0])} {_case_like(last, words[-1])}"
    else:
        rendered = _case_like(last, original)
    return rendered


def _case_like(value: str, model: str) -> str:
    if model.isupper():
        return value.upper()
    if model.islower():
        return value.lower()
    return value[:1].upper() + value[1:]


def _mask_identifier(value: str, counters: dict[str, int]) -> str:
    """Identifiers get a visible placeholder, not a plausible fake.

    An IBAN replaced by a well-formed IBAN invites someone downstream to
    treat it as real. A bracketed placeholder cannot be mistaken for data.

    Every placeholder is numbered, because two different real values that
    share one placeholder cannot be told apart on the way back: the
    document would come home with one of them in both places. That is a
    silent corruption, so uniqueness is a correctness requirement rather
    than a nicety.
    """
    label = _label_for(value)
    counters[label] = counters.get(label, 0) + 1
    index = counters[label]
    if label == "email":
        return f"adresse.masquee.{index}@example.invalid"
    return f"[{label} {index}]"


def _label_for(value: str) -> str:
    if "@" in value:
        return "email"
    # Address first, and months matched as whole words: "mars" is a
    # substring of "Marseille", which labelled every postcode line in the
    # sample as a date of birth.
    if _looks_like_an_address(value):
        return "adresse"
    words = {w.strip(",.;:").lower() for w in value.split()}
    if words & set(_MONTHS) or _looks_like_a_date(value):
        return "date de naissance"
    return "identifiant"


_MONTHS = (
    "janvier", "février", "fevrier", "mars", "avril", "mai", "juin", "juillet",
    "août", "aout", "septembre", "octobre", "novembre", "décembre", "decembre",
)
_STREET_WORDS = (
    "rue", "avenue", "boulevard", "impasse", "allée", "allee", "chemin",
    "route", "place", "cours", "quai", "voie", "résidence", "residence",
)


def _looks_like_a_date(value: str) -> bool:
    parts = value.replace("-", "/").replace(".", "/").split("/")
    return len(parts) == 3 and all(p.strip().isdigit() for p in parts)


def _looks_like_an_address(value: str) -> bool:
    lowered = value.lower()
    if any(word in lowered.split() for word in _STREET_WORDS):
        return True
    # A postcode and a town: five digits then a word.
    head, _, tail = value.partition(" ")
    return head.isdigit() and len(head) == 5 and bool(tail)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
