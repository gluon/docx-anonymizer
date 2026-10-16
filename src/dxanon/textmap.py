"""Run-aware text mapping and replacement for WordprocessingML.

Word splits a single visible word across several ``<w:t>`` runs for reasons
that have nothing to do with meaning: a spell-check boundary, an rsid, a
bold toggle.  ``DUPONT`` can be stored as ``DUP`` + ``ONT``.  Any approach
that edits one ``<w:t>`` at a time therefore misses most real matches.

This module concatenates the ``<w:t>`` nodes belonging to one paragraph
into a single string, records where each node sits in it, and writes
replacements back node by node.  Nothing but the ``<w:t>`` text is touched:
``<w:pPr>``, ``<w:rPr>``, bookmarks, fields and every other node are left
exactly as they were.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"

T = f"{{{W}}}t"
P = f"{{{W}}}p"
SPACE = f"{{{XML}}}space"


@dataclass(frozen=True)
class Span:
    """One ``<w:t>`` node and the slice of paragraph text it holds."""

    node: object
    start: int
    end: int


@dataclass(frozen=True)
class Edit:
    """Replace ``text[start:end]`` with ``replacement``."""

    start: int
    end: int
    replacement: str


class Paragraph:
    """The concatenated text of one paragraph, and how to write back to it."""

    def __init__(self, spans: list[Span], text: str) -> None:
        self.spans = spans
        self.text = text

    def apply(self, edits: list[Edit]) -> int:
        """Apply non-overlapping edits. Returns the number of nodes changed.

        A replacement is written in full into the node that holds its first
        character; the other nodes it spans simply lose their covered part.
        Word renders the result identically, and the replaced text inherits
        the formatting of the run where the match began.
        """
        edits = _validate(edits, len(self.text))
        if not edits:
            return 0

        changed = 0
        for span in self.spans:
            new_value = self._rebuild(span, edits)
            if new_value is None:
                continue
            _set_text(span.node, new_value)
            changed += 1
        return changed

    def _rebuild(self, span: Span, edits: list[Edit]) -> str | None:
        """New text for one node, or None when the node is untouched."""
        touching = [e for e in edits if e.start < span.end and e.end > span.start]
        # An edit that starts exactly at this node's end is written into the
        # NEXT node, not this one, so it does not touch this node at all.
        if not touching:
            return None

        parts: list[str] = []
        cursor = span.start
        for edit in touching:
            if edit.start > cursor:
                parts.append(self.text[cursor:min(edit.start, span.end)])
            if span.start <= edit.start < span.end:
                parts.append(edit.replacement)
            cursor = max(cursor, min(edit.end, span.end))
        if cursor < span.end:
            parts.append(self.text[cursor:span.end])

        new_value = "".join(parts)
        old_value = self.text[span.start:span.end]
        return None if new_value == old_value else new_value


def _validate(edits: list[Edit], length: int) -> list[Edit]:
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    previous_end = -1
    for edit in ordered:
        if edit.start < 0 or edit.end > length or edit.start > edit.end:
            raise ValueError(f"edit out of range: {edit}")
        if edit.start < previous_end:
            raise ValueError(f"overlapping edits near offset {edit.start}")
        previous_end = edit.end
    return ordered


def _set_text(node, value: str) -> None:
    node.text = value
    # Word drops leading and trailing whitespace unless the run says to keep
    # it.  We add the attribute when it becomes necessary and never remove
    # one that was already there.
    if value != value.strip() and node.get(SPACE) is None:
        node.set(SPACE, "preserve")


def paragraphs(root) -> list[Paragraph]:
    """Group every ``<w:t>`` in document order under its nearest ``<w:p>``.

    Grouping by nearest ancestor rather than by descent means text boxes
    (``<w:txbxContent>``), which nest paragraphs inside other paragraphs,
    are read once each instead of twice.  Nodes with no ``<w:p>`` ancestor
    at all are still grouped, so nothing is skipped.
    """
    groups: dict[int, list[Span]] = {}
    order: list[int] = []
    texts: dict[int, list[str]] = {}

    for node in root.iter(T):
        owner = _nearest_paragraph(node)
        key = id(owner) if owner is not None else id(root)
        if key not in groups:
            groups[key] = []
            texts[key] = []
            order.append(key)
        value = node.text or ""
        offset = sum(len(chunk) for chunk in texts[key])
        groups[key].append(Span(node=node, start=offset, end=offset + len(value)))
        texts[key].append(value)

    return [Paragraph(groups[key], "".join(texts[key])) for key in order]


def _nearest_paragraph(node):
    parent = node.getparent()
    while parent is not None:
        if parent.tag == P:
            return parent
        parent = parent.getparent()
    return None


def full_text(root) -> str:
    """Every paragraph's text, joined by newlines. For assertions and search."""
    return "\n".join(paragraph.text for paragraph in paragraphs(root))


def parse(data: bytes):
    parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    return etree.fromstring(data, parser)


def serialize(root, original: bytes) -> bytes:
    """Serialize, keeping the original XML declaration's exact spelling."""
    declaration = original[: original.find(b"?>") + 2] if original.startswith(b"<?xml") else b""
    body = etree.tostring(root, xml_declaration=False, encoding="UTF-8")
    if not declaration:
        return body
    tail = b"\r\n" if original[len(declaration):len(declaration) + 2] == b"\r\n" else b""
    return declaration + tail + body
