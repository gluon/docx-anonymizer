"""Everything a document says about who wrote it, not only what it says.

The grid used to be built from the text of the story parts alone. That
left a hole wide enough to walk a client through: a reviewer named only
in a ``w:author`` attribute, or an author named only in the file
properties, was never detected, so it never entered the table, so it was
never replaced, and the refusal check, which only looks for values in
the table, saw nothing to object to. The export went out with the name
in it.

These values are not candidates. Word does not put arbitrary words in
``w:author``: it puts the name of a person, taken from the installation
it was typed on. So they are handed to the grid as declared values,
certain and masked by default.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import detect, textmap
from .package import AUTHOR, INITIALS, PROPERTY_FIELDS, Package

#: Properties that name a person or a firm rather than describing the file.
_NAMING_FIELDS = tuple(
    field for field in PROPERTY_FIELDS
    if field.rsplit("}", 1)[-1] in ("creator", "lastModifiedBy", "Company", "Manager")
)

#: A file name says who the case is about more often than the body does.
_FILENAME_SPLIT = re.compile(r"[\s_\-.()\[\]]+")


def read_document(path) -> tuple[str, list[str], list[str]]:
    """The text to scan, the images to report, and the names to mask.

    Returns ``(text, images, identities)``. The text is what detection
    runs on; the identities are values already known to be names and are
    passed to the grid as declared.
    """
    package = Package.open(path)
    chunks = [textmap.full_text(textmap.parse(p.data)) for p in package.stories()]
    text = "\n".join(chunk for chunk in chunks if chunk)
    return text, [p.name for p in package.images()], identities(package, Path(path))


def identities(package: Package, path: Path | None = None) -> list[str]:
    """Names carried by the package itself, in document order, deduplicated."""
    found: list[str] = []

    for part in package.parts:
        if not part.name.endswith((".xml", ".rels")):
            continue
        try:
            root = textmap.parse(part.data)
        except Exception:
            continue

        for node in root.iter():
            # Authors and initials on comments and on every tracked change.
            for attribute in (AUTHOR, INITIALS):
                _add(found, node.get(attribute))
            if node.tag in _NAMING_FIELDS:
                _add(found, node.text)

    if path is not None:
        found.extend(_from_filename(path, found))
    return found


def _from_filename(path: Path, already: list[str]) -> list[str]:
    """Words of the file name that look like a name.

    "Dupont_conclusions_v3.docx" names the client in the one place a
    reader sees before opening anything.

    Less reliable than w:author, which Word fills with a person's name:
    a file name is also dates, version numbers and office vocabulary. So
    the words are filtered through the same lexicon detection uses, and
    what gets through is what no list recognises, which is the shape of
    a proper noun. A generic word the lexicon does not know will still
    get through and be offered as a name; the grid is where that is
    caught.
    """
    taken: list[str] = []
    for word in _FILENAME_SPLIT.split(path.stem):
        if len(word) <= 2 or not word[:1].isupper() or word in already:
            continue
        # "Dossier_Benzaoui_Confidentiel.docx" is three capitalised words
        # and one name. Without this, "Dossier" entered the table as a
        # certain name and the header came out reading "Marc FORESTIER
        # BENZAOUI". The lexicon already knows the vocabulary a case file
        # is named with; it is the same list detection uses.
        if detect._is_excluded(word):
            continue
        taken.append(word)
    return taken


def _add(found: list[str], value: str | None) -> None:
    value = (value or "").strip()
    if value and value not in found:
        found.append(value)
