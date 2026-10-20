"""Reading a PDF, which is two different documents wearing one extension.

A piece that arrives as a PDF is either a letter exported from a word
processor, whose characters are in the file and can be read exactly, or
a photograph of paper, whose characters are not there at all. The same
icon, the same extension, and opposite consequences: the first is as
reliable as a .docx, the second carries every risk of a scan, starting
with a misread name that nothing downstream can catch.

So this reads a PDF page by page and says which it was. A page with text
is extracted; a page without is rendered and handed to
:mod:`dxanon.ocr`. A document where any page had to be rendered counts as
scanned, which is what makes its piece wait for a person to read it.

**On the choice of library.** The obvious one for this is PyMuPDF, and
it is licensed AGPL: bundling it in an executable that is handed to
somebody would put the whole program under that licence. This repository
carries no licence of its own, which is a decision not yet taken rather
than a permissive one, so taking it by accident through a dependency
would be the wrong order. ``pypdfium2`` wraps Google's PDFium under
Apache 2.0 and BSD, does both halves of the job, and leaves the question
open.

Nothing here reaches the network, and nothing is written to disk: a page
is rendered into memory and passed to the engine as an array. A scan
written to a temporary file would be the client's document, in clear, in
a folder nobody cleans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import ocr

#: Below this many characters, a page is treated as an image of text
#: rather than text. A scanned page is rarely perfectly empty: a header
#: stamped by the scanner, a page number, a watermark can all leave a
#: handful of characters behind, and a page with nothing but those is a
#: page nobody can read without recognition.
MIN_CHARACTERS = 40

#: Rendering scale. PDFium renders at 72 dpi by default, which no engine
#: reads; 3 puts it at 216 dpi, which is the usual advice for
#: recognition and keeps a page under a few megabytes in memory.
SCALE = 3


@dataclass
class Reading:
    """What a PDF gave, and how much of it had to be recognised."""

    text: str = ""
    pages: int = 0
    recognised: list[int] = field(default_factory=list)
    doubtful: list[str] = field(default_factory=list)

    @property
    def scanned(self) -> bool:
        """Whether any page came from recognition rather than from text."""
        return bool(self.recognised)


class Unavailable(RuntimeError):
    """No PDF support in this build."""


_cached = None


def _document():
    global _cached
    if _cached is not None:
        return _cached
    try:
        import pypdfium2
    except ImportError as error:  # pragma: no cover - depends on the build
        raise Unavailable(f"paquet absent du build : {error}") from error
    _cached = pypdfium2
    return _cached


def diagnosis() -> str:
    """Empty when a PDF can be read, and why not when it cannot."""
    try:
        _document()
    except Unavailable as error:
        return str(error)
    return ""


def available() -> bool:
    return not diagnosis()


def read(path, recognise: bool = True) -> Reading:
    """Read every page: its text where there is text, its image otherwise.

    ``recognise`` set to False reads only what is really text and
    ignores the rest, which is what a build without a recognition engine
    can honestly do: a PDF of six typed pages and one scanned annex is
    then six pages of exact text and one page missing, and the window
    says which.
    """
    pypdfium2 = _document()
    document = pypdfium2.PdfDocument(str(Path(path)))
    try:
        chunks: list[str] = []
        reading = Reading(pages=len(document))
        for number, page in enumerate(document, start=1):
            text = _text_of(page)
            if len(text.strip()) >= MIN_CHARACTERS or not recognise:
                chunks.append(text)
                continue
            recognised = _recognise(page)
            if recognised.text.strip():
                reading.recognised.append(number)
                reading.doubtful.extend(recognised.doubtful)
                chunks.append(recognised.text)
            else:
                # Neither text nor anything readable in the image. Kept
                # as a page rather than dropped silently, because a page
                # that vanished between the file and the grid is a page
                # nobody thinks to look for.
                chunks.append(text)
        reading.text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
        return reading
    finally:
        document.close()


def _text_of(page) -> str:
    textpage = page.get_textpage()
    try:
        return textpage.get_text_range()
    finally:
        textpage.close()


def _recognise(page) -> ocr.Reading:
    """Render one page into memory and recognise it.

    Into memory, and not through a temporary file: that file would be a
    page of the client's document, in clear, in a folder nobody cleans.
    """
    if not ocr.available():
        return ocr.Reading()
    bitmap = page.render(scale=SCALE)
    try:
        return ocr.read(bitmap.to_numpy())
    finally:
        bitmap.close()
