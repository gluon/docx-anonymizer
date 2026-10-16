"""The pasted-text mode.

The common case, and the simpler one: a mail, an extract, a question.
Nothing to preserve but the characters, so there is no markup to protect,
no metadata to clean and no package to rebuild. The same table and the
same refusal check as the file mode, so the two cannot drift apart.
"""

from __future__ import annotations

from .engine import RefusedExport, Residue, _replace_all
from .mapping import Mapping


def anonymize(text: str, mapping: Mapping) -> str:
    """Mask, then read the result back before handing it over."""
    masked = _replace(text, mapping.forward())

    residues = [
        Residue(value=entry.real, where="le texte anonymisé")
        for entry in mapping.entries
        if entry.real and entry.real in masked
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
    missing = [e.pseudonym for e in mapping.entries if e.pseudonym and e.pseudonym not in text]
    if missing and require_all:
        raise RefusedExport([Residue(value=v, where="absent du texte renvoyé") for v in missing])
    return _replace(text, mapping.backward()), missing


#: Shared with the file mode on purpose: one substitution rule, so the two
#: entry points cannot drift apart.
_replace = _replace_all
