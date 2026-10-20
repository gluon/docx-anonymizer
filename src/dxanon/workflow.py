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
    #: Which pieces of a case the value appears in. Empty for a single
    #: document, where the question does not arise. It is shown rather
    #: than used: a name that turns up in one piece out of nine is worth
    #: a second look, and a name in all nine rarely is.
    pieces: tuple[str, ...] = ()

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
    rows.extend(_declared_but_unseen(rows, known or []))
    _assign(rows, text)
    return Grid(rows=rows, images=list(images or []))


def build_many(sources: list[tuple[str, str, list[str]]]) -> Grid:
    """One grid, and one pseudonym per subject, across several documents.

    A case is not a pile of independent documents. Masking each one on
    its own gives the client a different name in the conclusions and in
    the mail thread, and an AI asked to follow an argument across both
    reads two people. So detection runs per document, where it has to:
    positions, citation zones and declared identities are local. Only the
    rows are then merged, and the pseudonyms are drawn once, against the
    text of every document at once, so an invented name cannot collide
    with a word sitting in a piece nobody looked at.

    ``sources`` is (label, text, declared identities) per document.
    """
    merged: dict[str, Row] = {}
    for label, text, known in sources:
        for value, certainty, why, count, kind in detect.group(detect.find(text, known=known)):
            _merge_row(merged, label, Row(
                value=value, certainty=certainty, why=why, occurrences=count,
                decision=DEFAULTS[certainty], kind=kind, pieces=(label,),
            ))
        for row in _declared_but_unseen(list(merged.values()), known):
            _merge_row(merged, label, row)

    rows = list(merged.values())
    for row in rows:
        row.decision = DEFAULTS[row.certainty]
    _assign(rows, "\n".join(text for _, text, _ in sources))
    return Grid(rows=rows)


def _merge_row(merged: dict[str, Row], label: str, row: Row) -> None:
    """Fold one document's row into the case's row for the same value.

    Certainty is merged the way it is merged within one document, and for
    the same reason: arithmetic wins, and "party to a cited judgment"
    survives only if every appearance of the value, in every piece, sits
    inside a citation. A name that is a cited party in one document and
    the client in another is the client.
    """
    existing = merged.get(row.value)
    if existing is None:
        merged[row.value] = row
        if label not in row.pieces:
            row.pieces = row.pieces + (label,)
        return

    existing.occurrences += row.occurrences
    if label not in existing.pieces:
        existing.pieces = existing.pieces + (label,)
    if row.certainty is Certainty.CERTAIN:
        existing.certainty, existing.why = row.certainty, row.why
    elif existing.certainty is Certainty.CASE_LAW and row.certainty is not Certainty.CASE_LAW:
        existing.certainty, existing.why = row.certainty, row.why
    if existing.kind == "candidate" and row.kind != "candidate":
        existing.kind = row.kind


def _declared_but_unseen(rows: list[Row], known: list[str]) -> list[Row]:
    """Rows for names the document carries but never prints.

    A reviewer named only in a ``w:author`` attribute, or an author named
    only in the file properties, appears nowhere in the body. Detection
    reads the body, so it found nothing, the name never entered the
    table, and the refusal check, which only looks for what the table
    holds, had nothing to object to: the export went out with the name
    in it.

    Certain rather than candidates. Word does not put arbitrary words in
    ``w:author``; it puts the name of a person, taken from the
    installation the document was typed on.
    """
    seen = {row.value for row in rows}
    extra: list[Row] = []
    for value in known:
        if value in seen:
            continue
        seen.add(value)
        extra.append(Row(
            value=value, certainty=Certainty.CERTAIN,
            why="nom porté par le fichier lui-même, invisible dans le texte",
            occurrences=0, decision=Decision.REPLACE, kind="author",
        ))
    return extra


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

    links = _email_links(rows)
    groups = _group_rows(maskable, links)
    for members in groups:
        spine = _spine(members, links)
        kind = _kind_for_group(members, text)
        rendered = _render_group(members, spine, kind, taken, text)
        for member in members:
            member.group = spine
            member.pseudonym = rendered[member.value]
        # Reserved once the whole group is rendered, and not row by row.
        # Reserving as we went made a group collide with itself: "Sophie
        # LENOIR" reserved the word "LEMOINE", so the very next spelling,
        # "LENOIR", could not have it and was handed "LEMOINE 2", which
        # is what the document then said, in a pleading: "le licenciement
        # de Madame LEMOINE 2".
        for pseudonym in rendered.values():
            taken.add(pseudonym)
            # Reserve the individual words too, so no other subject is
            # given a name that is a word of this one. Without this,
            # "Camille" became "Bruno" while another person became
            # "Bruno Delacroix": a model shortening that to "le Docteur
            # Bruno" would have had it restored as "le Docteur Camille",
            # silently and with no way to notice.
            taken.update(pseudonym.split())


def _spine(members: list[Row], links: list[tuple[str, ...]]) -> str:
    """The spelling whose words order the whole group's pseudonym.

    Normally the longest spelling: every shorter one is a slice of it, so
    rendering from it keeps the same invented word on the same real word.

    When an address joined the group instead, no spelling holds all the
    words. "Sophie" and "Lenoir" are one person and one token each, so
    whichever was picked gave both rows the same slot, and both were
    rendered as the same first name, the second one numbered. The address
    carries the order the prose never wrote, so it becomes the spine.
    """
    longest = max(members, key=lambda r: len(_tokens(r.value)))
    words = _tokens(longest.value)
    present = {token for member in members for token in _tokens(member.value)}
    for link in links:
        folded = {_fold(part).upper() for part in link}
        if len(folded) > len(words) and folded <= present:
            return " ".join(link)
    return longest.value


def _render_group(
    members: list[Row], longest: str, kind: str, taken: set[str], text: str,
) -> dict[str, str]:
    """Pseudonyms for every spelling of one subject, drawn from one base.

    If any rendering is already somebody else's, the whole base is thrown
    away and another drawn, rather than patching the collision with a
    numbered suffix: the suffix ends up in the finished document, where a
    reader meets "Madame LEMOINE 2" in a set of conclusions.

    A number is still the last resort, for the case the retries cannot
    fix: two different real values in one group rendering to the same
    string. Two real values sharing a pseudonym cannot be told apart on
    the way back, so one of them would come home in both places.
    """
    refused: set[str] = set()
    for _ in range(len(members) + 8):
        base = _base_for(longest, kind, taken | refused, text)
        rendered = {m.value: _render_like(base, longest, m.value) for m in members}
        clashes = {p for p in rendered.values() if p in taken}
        if not clashes:
            seen: dict[str, str] = {}
            for value, pseudonym in rendered.items():
                if pseudonym in seen.values():
                    pseudonym = _unique(pseudonym, set(seen.values()) | taken)
                seen[value] = pseudonym
            return seen
        refused |= {word for p in clashes for word in p.split()}
    return {m.value: _unique(_render_like(base, longest, m.value), taken) for m in members}


#: Local parts that name a function rather than a person.
_FUNCTION_MAILBOXES = frozenset({
    "CONTACT", "CONTACTS", "INFO", "INFOS", "ACCUEIL", "SECRETARIAT", "CABINET",
    "ADMIN", "SERVICE", "SERVICES", "COMMERCIAL", "DIRECTION", "RESSOURCES",
    "NOREPLY", "NEPASREPONDRE", "FACTURATION", "COMPTABILITE", "GREFFE",
})


def _email_links(rows: list[Row]) -> list[tuple[str, ...]]:
    """Words that one address says belong to one person.

    A mail thread writes a client as "Sophie" in one line and "Mme
    Lenoir" in another, and never once writes both words together. No
    row contains the other, so the grouping by words could not see one
    person and invented two, each with its own pseudonym: the same woman
    appeared twice in the masked text under different names.

    Her address says what the prose does not. Only a local part of
    exactly two parts is used, and neither may name a function: three
    parts or more is as often a shared mailbox, and merging two partners
    of a firm into one person would be worse than the split it fixes.
    """
    links: list[tuple[str, ...]] = []
    for row in rows:
        if row.kind != "email":
            continue
        local = row.value.split("@")[0]
        parts = tuple(p for p in re.split(r"[._+-]", local) if len(p) >= 4)
        if len(parts) != 2:
            continue
        if {_fold(p).upper() for p in parts} & _FUNCTION_MAILBOXES:
            continue
        links.append(parts)
    return links


def add_by_hand(grid: Grid, value: str, text: str = "") -> Row:
    """Mask something the detection never offered.

    Over-detection is exhaustive for capitalised names and nothing else:
    a nickname, a job title that identifies one person in a small firm, a
    machine number, a date that only means something to the parties. The
    user sees those and the program never will, so the grid has to take
    them.

    Certain by construction. Someone selected it on purpose; there is
    nothing left to confirm.

    A value that shares a word with a subject already in the grid joins
    it and is rendered from the same invented name, which is the whole
    reason this cannot be a separate little table on the side: "Lenoir"
    added by hand next to "Sophie LENOIR" has to come out as the same
    woman, not as a second one.
    """
    value = value.strip()
    if not value:
        raise ValueError("rien à masquer")

    existing = next((row for row in grid.rows if row.value == value), None)
    if existing is not None:
        existing.decision = Decision.REPLACE
        return existing

    row = Row(
        value=value, certainty=Certainty.CERTAIN, why="choisi à la main",
        occurrences=text.count(value), decision=Decision.REPLACE,
        kind="name" if _looks_like_a_name(value) else "reference",
    )
    taken = {r.pseudonym for r in grid.rows if r.pseudonym}
    taken |= {word for r in grid.rows if r.pseudonym for word in r.pseudonym.split()}

    # Not everything worth masking is a name. "ligne 4" was handed
    # "olivier Forestier", and the masked text read "sur la olivier
    # Forestier": a placeholder cannot be mistaken for prose, and prose
    # that reads as nonsense is prose the reader stops trusting.
    if not row.is_person_like:
        row.pseudonym = _mask_identifier(value, _counters_in(grid))
        grid.rows.append(row)
        return row

    tokens = _tokens(value)
    siblings = [r for r in grid.rows
                if r.pseudonym and r.is_person_like and _tokens(r.value) & tokens]
    if siblings:
        spine = max(siblings, key=lambda r: len(_tokens(r.value)))
        row.group = spine.group or spine.value
        row.pseudonym = _render_like(spine.pseudonym.split(), spine.value, value)
    else:
        kind = _kind_from_context(value, text) or "name"
        base = _base_for(value, kind, taken, text)
        row.group = value
        row.pseudonym = _unique(_render_like(base, value, value), taken)

    grid.rows.append(row)
    return row


def _looks_like_a_name(value: str) -> bool:
    """Whether a hand-picked value can carry an invented name.

    Every word capitalised and no digit anywhere. Deliberately crude:
    the cost of being wrong is a placeholder where a name would have
    read better, and the cost the other way is a sentence that reads as
    nonsense.
    """
    words = value.split()
    return bool(words) and all(
        word[:1].isupper() and not any(ch.isdigit() for ch in word) for word in words
    )


def _counters_in(grid: Grid) -> dict[str, int]:
    """The placeholder numbers already in use, so the next one is free.

    Two values sharing a placeholder cannot be told apart on the way
    back: the document would come home with one of them in both places.
    """
    counters: dict[str, int] = {}
    for row in grid.rows:
        found = re.fullmatch(r"\[(.+) (\d+)\]", row.pseudonym or "")
        if found:
            label, number = found.group(1), int(found.group(2))
            counters[label] = max(counters.get(label, 0), number)
    return counters


def _group_rows(rows: list[Row], links: list[frozenset[str]] | None = None) -> list[list[Row]]:
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

    # An address can say that two values are one person even when no row
    # contains the other: see :func:`_email_links`.
    for link in links or []:
        folded = {_fold(part).upper() for part in link}
        members = [i for i, words in enumerate(tokens) if words & folded]
        for other in members[1:]:
            parents[root(other)] = root(members[0])

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
    r"(?:\b\d{5}\s+|\bà\s+|\bau\s+|\bBarreau\s+(?:de|d['’])\s*|\bCA\s+"
    # A court is named after its town, and the formulas that name one are
    # fixed: "CONSEIL DE PRUD'HOMMES DE MARSEILLE" gave the town a first
    # name, and the masked pleading was addressed to "PRUD'HOMMES DE
    # DAMIEN".
    r"|\b(?:prud['’]hommes|pr[uû]d|cour\s+d['’]appel|tribunal[^.\n]{0,30}|"
    r"conseil[^.\n]{0,30}|commune|ville|mairie|barreau)\s+(?:de\s+|du\s+|d['’])"
    # A place is also named after the word that says it is one, with no
    # "de" between: "secteur Beaumont" was given a first name.
    r"|\b(?:secteur|zone|site|quartier|r[ée]gion|d[ée]partement)\s+)$",
    re.IGNORECASE,
)
_ORG_BEFORE = re.compile(
    r"\b(?:SAS|SASU|SARL|EURL|SA|SCI|SNC|SCOP|SCP|SELARL|GIE|soci[ée]t[ée]|Ste|St[ée]|"
    r"entreprise|groupe|cabinet|[ée]tude|association|f[ée]d[ée]ration|syndicat|"
    r"union|mutuelle|caisse|agence|service)\s+$",
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
    # The longest spelling decides, and it decides alone. A short form is
    # ambiguous by nature: "Moreau" is preceded by "Cabinet" in one line
    # and names the lawyer in the next, and letting it vote turned
    # "Claire Moreau" into "Orion Industries", so the footer read "Orion
    # Industries, avocate". The long form carries the information.
    longest = max(members, key=lambda r: len(_tokens(r.value)))
    if len(_tokens(longest.value)) > 1:
        explicit = _kind_from_context(longest.value, text)
        # Silence on the long form means a person: that is the common
        # case, and a person's name still reads correctly after
        # "Cabinet", where a company name does not read at all before
        # "avocate".
        return explicit or "name"

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
    if _looks_like_org(value):
        return "org"
    # A domain name says what the prose left out. "delivree par Thermopack
    # Industrie" carries no form of company, so the employer read as a
    # person and was given a first name; the same file writes
    # "k.benhaddou@thermopack-industrie.fr", and a word in a domain
    # belongs to an organisation. Read from the domain only, never the
    # local part, which is usually a person.
    return "org" if _in_a_domain(value, text) else None


def _in_a_domain(value: str, text: str) -> bool:
    if len(_tokens(value)) != 1:
        return False
    word = _fold(value).casefold()
    return any(word in _fold(domain).casefold()
               for domain in re.findall(r"@([\w.-]+\.[A-Za-z]{2,})", text))


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
        #
        # Checked against the document, which every other generated word
        # already was. This one was not, and "Industries" was handed to a
        # company in a file that says "Section Industrie": the pseudonym
        # then contained a value the table wanted masked, the coherence
        # check said so, and the export was refused on a conflict the
        # program had created itself.
        return _activity_word(position, taken, text)
    return propose("place", taken, text=text)


def _activity_word(position: int, taken: set[str], text: str) -> str:
    folded_text = _fold(text).casefold()
    folded_taken = {_fold(t).casefold() for t in taken}
    order = range(position, position + len(_ACTIVITY_WORDS))
    for index in order:
        word = _ACTIVITY_WORDS[index % len(_ACTIVITY_WORDS)]
        folded = _fold(word).casefold()
        if folded in folded_taken:
            continue
        # Substring, not whole word: "Industries" has to be refused in a
        # document that contains "Industrie", since the check that
        # refuses an export reads the one inside the other.
        if folded_text and (folded in folded_text or any(
            part and part in folded for part in folded_text.split()
            if len(part) > 4
        )):
            continue
        return word
    return _ACTIVITY_WORDS[position % len(_ACTIVITY_WORDS)]


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
    if detect.REFERENCE.fullmatch(value):
        return "référence"
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
