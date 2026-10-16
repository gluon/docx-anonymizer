"""Reading and writing the .docx container without disturbing it.

A .docx is a zip of XML parts.  Identity hides in more of them than the
body: headers, footers, footnotes, comments (including each comment's
author and initials), the author stamped on every tracked change, and the
file properties.  This module enumerates those parts and rewrites only the
ones that actually changed, copying every other entry byte for byte so the
package stays as Word wrote it.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
AUTHOR = f"{{{W}}}author"
INITIALS = f"{{{W}}}initials"

#: Parts whose <w:t> nodes carry visible document text.
STORY_PATTERNS = (
    re.compile(r"^word/document\d*\.xml$"),
    re.compile(r"^word/header\d*\.xml$"),
    re.compile(r"^word/footer\d*\.xml$"),
    re.compile(r"^word/footnotes\.xml$"),
    re.compile(r"^word/endnotes\.xml$"),
    re.compile(r"^word/comments\.xml$"),
    re.compile(r"^word/commentsExtended\.xml$"),
    re.compile(r"^word/glossary/document\.xml$"),
)

#: Property parts: free text fields rather than runs.
PROPERTY_PARTS = ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml")

#: Property fields that routinely carry a person's or a firm's name.
PROPERTY_FIELDS = (
    "{http://purl.org/dc/elements/1.1/}creator",
    "{http://purl.org/dc/elements/1.1/}title",
    "{http://purl.org/dc/elements/1.1/}subject",
    "{http://purl.org/dc/elements/1.1/}description",
    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy",
    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}keywords",
    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}category",
    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Company",
    "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Manager",
)

IMAGE_PATTERN = re.compile(r"^word/media/", re.IGNORECASE)


@dataclass
class Part:
    name: str
    data: bytes
    info: zipfile.ZipInfo
    dirty: bool = False


@dataclass
class Package:
    """Every entry of the .docx, in the order the zip stores them."""

    parts: list[Part] = field(default_factory=list)
    comment: bytes = b""

    @classmethod
    def open(cls, path) -> "Package":
        parts: list[Part] = []
        with zipfile.ZipFile(path) as archive:
            comment = archive.comment
            for info in archive.infolist():
                parts.append(Part(name=info.filename, data=archive.read(info), info=info))
        return cls(parts=parts, comment=comment)

    def save(self, path) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.comment = self.comment
            for part in self.parts:
                # Reuse the original ZipInfo so timestamps, external attributes
                # and the compression method survive untouched.
                info = zipfile.ZipInfo(part.info.filename, date_time=part.info.date_time)
                info.compress_type = part.info.compress_type
                info.external_attr = part.info.external_attr
                info.internal_attr = part.info.internal_attr
                info.create_system = part.info.create_system
                archive.writestr(info, part.data)

    def get(self, name: str) -> Part | None:
        for part in self.parts:
            if part.name == name:
                return part
        return None

    def stories(self) -> list[Part]:
        return [p for p in self.parts if any(r.match(p.name) for r in STORY_PATTERNS)]

    def properties(self) -> list[Part]:
        return [p for p in self.parts if p.name in PROPERTY_PARTS]

    def images(self) -> list[Part]:
        """Images are reported, never altered: the tool cannot read their text."""
        return [p for p in self.parts if IMAGE_PATTERN.match(p.name)]
