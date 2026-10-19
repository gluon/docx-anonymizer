"""The pasted-text mode.

The common case, and the simpler one: a mail, an extract, a question.
Nothing to preserve but the characters, so there is no markup to protect,
no metadata to clean and no package to rebuild. The same table and the
same refusal check as the file mode, so the two cannot drift apart.
"""

from __future__ import annotations

from .engine import RefusedExport, Residue, _occurs, _replace_all, refuse_empty
from .mapping import Mapping


def anonymize(text: str, mapping: Mapping) -> str:
    """Mask, then read the result back before handing it over.

    Records which entries actually fired. An entry can legitimately never
    apply: a name declared for the case but absent from this extract, or
    a short form only ever seen inside a longer one, which is replaced
    first. Without that record the return trip refuses a perfectly good
    document because a pseudonym it never wrote is "missing".
    """
    refuse_empty(mapping)
    mapping.mark_used(_applied(text, mapping.forward()))
    masked = _replace(text, mapping.forward())

    # Word by word, exactly as the file mode reads its output back: a
    # value found inside a longer word is not an occurrence of it, and
    # treating it as one refused clean documents.
    residues = [
        Residue(value=entry.real, where="le texte anonymisé")
        for entry in mapping.entries
        if entry.real and _occurs(entry.real, masked)
    ]
    if residues:
        raise RefusedExport(residues)
    return masked


def deanonymize(text: str, mapping: Mapping, require_all: bool = True) -> tuple[str, list[str]]:
    """Restore, and report pseudonyms that never came back.

    As in the file mode, the failure that matters is a pseudonym the model
    reworded: it matches nothing and is silently never restored. It can
    only be seen as an absence, so the check runs before substituting.
    """
    missing = [
        e.pseudonym
        for e in mapping.entries
        if e.pseudonym and mapping.was_used(e) and e.pseudonym not in text
    ]
    if missing and require_all:
        raise RefusedExport([Residue(value=v, where="absent du texte renvoyé") for v in missing])
    return _replace(text, mapping.backward()), missing


#: Shared with the file mode on purpose: one substitution rule, so the two
#: entry points cannot drift apart.
_replace = _replace_all


def _applied(text: str, pairs: list[tuple[str, str]]) -> set[str]:
    """Which sources the substitution pass would actually consume.

    Walked the same way the substitution walks, because "is this string
    present in the text" gives a different answer: a short form sitting
    inside a longer one is present but never replaced, the longer pair
    having already consumed those characters.
    """
    used: set[str] = set()
    index = 0
    while index < len(text):
        for source, _ in pairs:
            if source and text.startswith(source, index):
                used.add(source)
                index += len(source)
                break
        else:
            index += 1
    return used
