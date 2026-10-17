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


def build(
    text: str,
    known: list[str] | None = None,
    images: list[str] | None = None,
) -> Grid:
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
    maskable: list[Row] = []
    for row in rows:
        if row.decision is Decision.KEEP:
            continue
        if not row.is_person_like:
            row.pseudonym = _mask_identifier(row.value, counters)
            taken.add(row.pseudonym)
            continue
        maskable.append(row)

    groups = _group_rows(maskable)
    for members in groups:
        longest = max(members, key=lambda r: len(_tokens(r.value)))
        kind = _kind_for_group(members, text)
        base = _base_for(longest.value, kind, taken, text)
        for member in members:
            member.group = longest.value
            member.pseudonym = _unique(_render_like(base, longest.value, member.value), taken)
            taken.add(member.pseudonym)
            # Reserve the individual words too, so no other subject is
            # given a name that is a word of this one. Without this,
            # "Camille" became "Bruno" while another person became
            # "Bruno Delacroix": a model shortening that to "le Docteur
            # Bruno" would have had it restored as "le Docteur Camille",
            # silently and with no way to notice.
            taken.update(member.pseudonym.split())


def _group_rows(rows: list[Row]) -> list[list[Row]]:
    """Put every spelling of one subject in one group.

    Two values belong together when the words of one are contained in the
    words of the other. That joins "Jean DUPONT" with "DUPONT" and with
    "Dupont", and it also joins "TRANSPORTS FRIGORIFIQUES DU LITTORAL"
    with "Transports Frigorifiques" and with "Littoral", which the older
    rule, keyed on the last word alone, split into three companies with
    three unrelated pseudonyms.

    It will also join two unrelated people who share a surname. That is
    visible in the grid and the user can correct it; the opposite error,
    one subject silently becoming three, is not visible at all.
    """
    parents = list(range(len(rows)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    tokens = [_tokens(row.value) for row in rows]
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if not tokens[i] or not tokens[j]:
                continue
            if tokens[i] <= tokens[j] or tokens[j] <= tokens[i]:
                parents[root(i)] = root(j)

    grouped: dict[int, list[Row]] = {}
    for index, row in enumerate(rows):
        grouped.setdefault(root(index), []).append(row)
    return list(grouped.values())


#: Words that carry no identity and must not, on their own, make two
#: values look related: "Transports DE France" and "Societe DE Paris".
_EMPTY_WORDS = frozenset({"DE", "DU", "DES", "LA", "LE", "LES", "ET", "D", "L", "AU", "AUX"})


def _tokens(value: str) -> frozenset[str]:
    words = _fold(value).upper().replace("'", " ").replace("’", " ").split()
    return frozenset(w for w in words if w and w not in _EMPTY_WORDS)


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


def _kind_for_group(members: list[Row], text: str) -> str:
    """Decide what the subject is from all its spellings at once.

    "TRANSPORTS FRIGORIFIQUES DU LITTORAL" is preceded by "la société"
    exactly once in a thousand words; its two shorter spellings are
    preceded by nothing in particular. Voting per row let the majority of
    silent mentions win and handed a haulage company a person's name.
    """
    votes: dict[str, int] = {}
    for member in members:
        kind = _kind_from_context(member.value, text)
        if kind is not None:
            votes[kind] = votes.get(kind, 0) + member.occurrences

    # A single explicit marker outweighs any number of silent mentions:
    # "la société X" says what X is, "X conteste" says nothing.
    for explicit in ("org", "place"):
        if explicit in votes:
            return explicit
    if votes:
        return max(votes.items(), key=lambda item: item[1])[0]
    # Only now, with nothing in the sentences to go on, does the shape of
    # the word decide. Judged across every spelling at once: a surname in
    # capitals looks exactly like an initialism until you notice the same
    # subject also appears as "Dupont".
    if all(_looks_like_acronym(m.value) for m in members):
        return "acronym"
    return "name"


def _kind_from_context(value: str, text: str) -> str | None:
    """What the surrounding words say this name is, or None if they do not.

    Read from the text rather than guessed from the name itself, because
    a surname and a town look alike and only the context separates them.

    Returning None matters: an earlier version answered "name" when the
    sentences said nothing, that default was counted as a vote, and the
    vote then outranked every other clue. A bank came out as "son compte
    FABRICE".
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
    if _TOPONYM.match(value):
        return "place"
    return "org" if _looks_like_org(value) else None


#: A hyphenated Saint- or Mont- is a place far more often than a surname,
#: and a surname wrongly given a place name is a cosmetic error, where the
#: reverse reads as nonsense: "la zone de Romain".
_TOPONYM = re.compile(
    r"^(?:Saint|Sainte|St|Ste|Mont|Val|Ville|Villeneuve|Chateau|Château|"
    r"Bourg|Pont|Port|Neuville|Fontaine)[-\s]",
    re.IGNORECASE,
)


def _looks_like_acronym(value: str) -> bool:
    """BNP, URSSAF, SNCF: initials, not a person.

    Giving one a first name produced "son compte FABRICE", which stops a
    reader cold and tells them the text has been through a machine.
    """
    word = value.strip()
    return word.isupper() and word.isalpha() and 2 <= len(word) <= 5 and " " not in word


def _looks_like_org(value: str) -> bool:
    return len(value.split()) > 1 and value.upper() == value


def _base_for(longest: str, kind: str, taken: set[str], text: str) -> list[str]:
    """A pseudonym with as many words as the longest spelling of the subject.

    One word per real word, so every shorter spelling can be rendered
    from a slice of it and still read as the same subject.
    """
    needed = sum(1 for w in longest.split() if _fold(w).upper() not in _EMPTY_WORDS)
    base = propose(kind, taken, text=text).split()
    while len(base) < needed:
        base.append(_filler(kind, len(base), taken | set(base), text))
    return base[:needed] if needed else base


def _filler(kind: str, position: int, taken: set[str], text: str) -> str:
    """The next word of a multi-word pseudonym.

    A company's name usually runs activity then place: "TRANSPORTS
    FRIGORIFIQUES DU LITTORAL". Filling every slot from one pool gave
    "ORION INDUSTRIES DU SERVICES", which no reader would take for a
    company. Alternating puts a place where a place belongs.
    """
    if kind != "org":
        return propose(kind, taken, text=text).split()[-1]
    if position == 1:
        # Picked by position, not by how many pseudonyms exist so far.
        # Keying it on len(taken) made every name in the document depend
        # on how many rows the grid happened to hold, so adding one
        # detection silently renamed everything.
        return _ACTIVITY_WORDS[position % len(_ACTIVITY_WORDS)]
    return propose("place", taken, text=text)


#: Words that make an invented company name read like one.
_ACTIVITY_WORDS = (
    "Logistique", "Industries", "Services", "Distribution", "Technologies",
    "Partenaires", "Développement", "Solutions", "Conseil", "International",
)


def _render_like(base: list[str], longest: str, original: str) -> str:
    """Render one spelling from the group's base, aligned word by word.

    The subject's longest spelling fixes the order of the invented words,
    and every shorter spelling takes the invented words sitting at the
    positions of the real words it actually contains. So "TRANSPORTS
    FRIGORIFIQUES DU LITTORAL" becomes "ORION LOGISTIQUE DU VALMONT",
    "Transports Frigorifiques" becomes "Orion Logistique" and "Littoral"
    becomes "Valmont": the same company throughout, and three distinct
    strings, which is what lets the return trip tell them apart.

    Shape and case follow the original word for word, because a masked
    text that cannot keep a name straight is a text the reader stops
    trusting.
    """
    positions: dict[str, int] = {}
    index = 0
    for word in longest.split():
        folded = _fold(word).upper()
        if folded in _EMPTY_WORDS:
            continue
        positions.setdefault(folded, index)
        index += 1

    rendered: list[str] = []
    fallback = 0
    for word in original.split():
        folded = _fold(word).upper()
        if folded in _EMPTY_WORDS:
            rendered.append(word)
            continue
        slot = positions.get(folded)
        if slot is None:
            slot = fallback
            fallback += 1
        rendered.append(_case_like(base[min(slot, len(base) - 1)], word))
    return " ".join(rendered) if rendered else base[0]


def _unique(candidate: str, taken: set[str]) -> str:
    """Two subjects must never share a pseudonym.

    They cannot be told apart on the way back, so the document would come
    home with one of them in both places, silently.
    """
    if candidate not in taken:
        return candidate
    for suffix in range(2, 500):
        numbered = f"{candidate} {suffix}"
        if numbered not in taken:
            return numbered
    raise RuntimeError("no free pseudonym left, which should be impossible")


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
