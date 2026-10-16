"""Anonymise and restore, with a refusal check on the way out.

The guarantee this tool offers is not that detection is perfect.  It is
that nothing leaves without being checked: before writing anything, the
engine reads back what it just produced and looks for every real value it
knows about.  One hit and it writes nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import textmap
from .mapping import Mapping
from .package import AUTHOR, INITIALS, PROPERTY_FIELDS, W, Package, Part

TEXT_SUFFIXES = (".xml", ".rels")
INSTR_TEXT = f"{{{W}}}instrText"
RELATIONSHIP = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"


class RefusedExport(Exception):
    """Raised when a residue survives the substitution. Nothing is written."""

    def __init__(self, residues: list["Residue"]) -> None:
        self.residues = residues
        listing = "; ".join(f"{r.value!r} in {r.where}" for r in residues[:8])
        more = "" if len(residues) <= 8 else f" (+{len(residues) - 8} more)"
        super().__init__(f"export refused, {len(residues)} residue(s): {listing}{more}")


@dataclass(frozen=True)
class Residue:
    value: str
    where: str


@dataclass
class Report:
    replacements: int = 0
    parts_changed: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def anonymize(source, destination, mapping: Mapping) -> Report:
    package = Package.open(source)
    report = _substitute(package, mapping.forward())
    report.images = [p.name for p in package.images()]

    residues = scan(package, [e.real for e in mapping.entries])
    if residues:
        raise RefusedExport(residues)

    package.save(destination)
    return report


def deanonymize(source, destination, mapping: Mapping, require_all: bool = True) -> Report:
    """Put the real values back.

    The return trip fails differently from the outward one.  Looking for
    leftover pseudonyms afterwards proves nothing: the substitution just
    removed every one it could see, so the search is always empty.  The
    failure that matters is a pseudonym the model or the user *reworded*,
    ``Marc Lemoine`` coming back as ``Marc Lemoyne``.  That no longer
    matches anything, so it is never restored, and the document would go
    out half real and half invented.

    The only way to see it is from the other end: a pseudonym that is in
    the table and nowhere in the returned document.  So that is what is
    checked, before substituting.  ``require_all=False`` is for the case
    where only an extract came back, and the gaps are expected.
    """
    package = Package.open(source)

    pseudonyms = [e.pseudonym for e in mapping.entries if e.pseudonym]
    present = {r.value for r in scan(package, pseudonyms)}
    missing = [p for p in pseudonyms if p not in present]

    if missing and require_all:
        raise RefusedExport([Residue(value=v, where="not found in the returned document") for v in missing])

    report = _substitute(package, mapping.backward())
    report.unresolved = missing
    package.save(destination)
    return report


def _substitute(package: Package, pairs: list[tuple[str, str]]) -> Report:
    report = Report()
    if not pairs:
        return report

    for part in package.parts:
        if not part.name.endswith(TEXT_SUFFIXES):
            continue
        try:
            root = textmap.parse(part.data)
        except Exception:
            continue

        count = 0
        count += _substitute_runs(root, pairs)
        count += _substitute_attributes(root, pairs)
        count += _substitute_fields(root, pairs)
        count += _substitute_instructions(root, pairs)
        count += _substitute_relationships(root, pairs)

        if count:
            part.data = textmap.serialize(root, part.data)
            part.dirty = True
            report.replacements += count
            report.parts_changed.append(part.name)

    return report


def _substitute_runs(root, pairs: list[tuple[str, str]]) -> int:
    count = 0
    for paragraph in textmap.paragraphs(root):
        edits = _find(paragraph.text, pairs)
        if edits:
            paragraph.apply(edits)
            count += len(edits)
    return count


def _substitute_attributes(root, pairs: list[tuple[str, str]]) -> int:
    """Authors and initials on comments and on every tracked change.

    A document reviewed in-house keeps the name of each reviewer attached
    to each correction.  It shows nowhere in the body and reads perfectly
    well in the file.
    """
    count = 0
    for node in root.iter():
        for attribute in (AUTHOR, INITIALS):
            value = node.get(attribute)
            if not value:
                continue
            replaced = _replace_all(value, pairs)
            if replaced != value:
                node.set(attribute, replaced)
                count += 1
    return count


def _substitute_fields(root, pairs: list[tuple[str, str]]) -> int:
    count = 0
    for node in root.iter():
        if node.tag not in PROPERTY_FIELDS or not node.text:
            continue
        replaced = _replace_all(node.text, pairs)
        if replaced != node.text:
            node.text = replaced
            count += 1
    return count


def _substitute_instructions(root, pairs: list[tuple[str, str]]) -> int:
    """Field codes: MERGEFIELD, HYPERLINK, AUTHOR and friends.

    ``<w:instrText>`` holds the code rather than the rendered result, so it
    is invisible in the body text yet perfectly readable in the file.
    """
    count = 0
    for node in root.iter(INSTR_TEXT):
        if not node.text:
            continue
        replaced = _replace_all(node.text, pairs)
        if replaced != node.text:
            node.text = replaced
            count += 1
    return count


def _substitute_relationships(root, pairs: list[tuple[str, str]]) -> int:
    """Relationship targets: a ``mailto:`` link carries a full address."""
    count = 0
    for node in root.iter(RELATIONSHIP):
        target = node.get("Target")
        if not target:
            continue
        replaced = _replace_all(target, pairs)
        if replaced != target:
            node.set("Target", replaced)
            count += 1
    return count


def _find(text: str, pairs: list[tuple[str, str]]) -> list[textmap.Edit]:
    """Non-overlapping matches, longest source first."""
    edits: list[textmap.Edit] = []
    taken: list[tuple[int, int]] = []
    for source, target in pairs:
        for match in re.finditer(re.escape(source), text):
            start, end = match.span()
            if any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            taken.append((start, end))
            edits.append(textmap.Edit(start=start, end=end, replacement=target))
    return edits


def _replace_all(value: str, pairs: list[tuple[str, str]]) -> str:
    for source, target in pairs:
        value = value.replace(source, target)
    return value


def scan(package: Package, values: list[str]) -> list[Residue]:
    """Look for any of ``values`` anywhere in the package.

    Story parts are scanned on their *reconstructed* paragraph text, not on
    raw XML: a name split across two runs reads as ``DUP</w:t>…<w:t>ONT``
    in the markup, so a raw search would declare the file clean while the
    name is plainly visible in Word.  Everything else is scanned raw, plus
    the entry names themselves, since a filename is often the most
    talkative part of a document.
    """
    wanted = [v for v in values if v]
    if not wanted:
        return []

    found: list[Residue] = []
    stories = {p.name for p in package.stories()}

    for part in package.parts:
        for value in wanted:
            if value in part.name:
                found.append(Residue(value=value, where=f"entry name {part.name}"))

        if not part.name.endswith(TEXT_SUFFIXES):
            continue

        haystacks = _haystacks(part, part.name in stories)
        for value in wanted:
            for label, haystack in haystacks:
                if value in haystack:
                    found.append(Residue(value=value, where=f"{part.name} ({label})"))
                    break
    return found


def _haystacks(part: Part, is_story: bool) -> list[tuple[str, str]]:
    raw = part.data.decode("utf-8", errors="replace")
    if not is_story:
        return [("raw", raw)]
    try:
        root = textmap.parse(part.data)
    except Exception:
        return [("raw", raw)]
    # Attribute values and property fields are not inside <w:t>, so the raw
    # pass still has to run alongside the reconstructed text.
    return [("text", textmap.full_text(root)), ("raw", raw)]
