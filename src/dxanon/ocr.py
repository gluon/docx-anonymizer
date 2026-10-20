"""Reading a scanned piece, on this machine.

A case file is half paper. A pay slip, a warning letter, a medical
certificate arrive as a scan, and a scan carries names the rest of the
program cannot see: everything else here reads characters, and there are
none in an image.

What this does, and the shape of it matters: a scanned piece becomes a
*text* piece of the case. The scan itself never goes anywhere. The text
is read on this machine, checked by the person who knows the file, masked
like any other text, and it is the masked text that is submitted. Drawing
black rectangles over an image was the other option and it is worse on
both counts: it needs a canvas and a steady hand, and a model reads a
redacted scan badly, which was the whole reason for sending text.

Two things this module refuses to pretend.

**It is not a reader of handwriting.** A handwritten letter comes back as
noise, and noise that happens to contain a name is worse than nothing. So
nothing here is exported without being read by a person: see
:attr:`dxanon.case.Piece.reviewed`.

**It creates a leak this program did not have.** ``DUPONT`` misread as
``DUPQNT`` matches no rule, enters no row, and goes out in clear. The
refusal check cannot see it either, since it only looks for what the
table holds. The reading screen is the answer, and it is compulsory for a
piece that came from here.

The engine is bundled with the executable and runs offline. That is
asserted rather than assumed: ``tests/test_ocr.py`` runs a recognition
with the network guard installed and fails if anything tried to leave.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import detect

#: Extensions handled here. PDFs are not: rendering a page needs another
#: bundled dependency, and that is a separate decision with its own
#: weight. A PDF is exported to images by whatever produced it.
IMAGES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


@dataclass
class Reading:
    """What one scan gave, and how sure the engine was about it."""

    text: str = ""
    lines: list[tuple[str, float]] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        """The engine's own average, 0 when it read nothing."""
        if not self.lines:
            return 0.0
        return sum(score for _, score in self.lines) / len(self.lines)

    @property
    def doubtful(self) -> list[str]:
        """Lines the engine itself was unsure of, worst first.

        Shown to the reader rather than dropped. A line the engine
        doubts is exactly where a misread name hides, and a misread name
        is the one thing this module can introduce that the rest of the
        program cannot catch.
        """
        weak = [text for text, score in self.lines if score < 0.80]
        return sorted(weak, key=lambda line: len(line), reverse=True)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


#: Words the splitter is allowed to recognise inside a glued run.
#: Deliberately not the whole legal vocabulary: this is only ever used to
#: put back a space the engine dropped, and a long list means a word cut
#: in two because something was hiding in the middle of it. These are
#: the words that make a detection rule fire, which is the whole point
#: of putting the space back: a civility makes what follows a name, a
#: form of company makes it a company, a street word makes an address.
GLUE_WORDS = tuple(sorted(
    {
        _fold(word).upper()
        for word in (
            detect.CIVILITIES
            + detect.COMPANY_FORMS
            + ("rue", "avenue", "boulevard", "impasse", "allee", "allée",
               "chemin", "route", "place", "cours", "quai", "voie",
               "residence", "résidence", "lotissement", "zone")
            + ("industrie", "industries", "transports", "services",
               "logistique", "distribution", "technologies", "solutions",
               "partenaires", "international", "mutuelle", "cabinet",
               "association", "federation", "fédération", "syndicat")
        )
        if len(_fold(word)) >= 3
    },
    key=len, reverse=True,
))

#: Below this, what is left of a run after a word is peeled off is more
#: likely to be noise than a name.
_MIN_REMAINDER = 2

_DIGIT_BOUNDARY = re.compile(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)")


def respace(text: str) -> str:
    """Put back the spaces the engine dropped, where they can be known.

    Measured on a page of printed French, the engine returns one line
    perfectly spaced and the next soldered together:
    ``SASTHERMOPACKINDUSTRIE``, ``MADAMESOPHIE LENOIR``,
    ``27BOULEVARDCHAVE,13005MARSEILLE``. The recognition model shipped
    with the engine is trained for Chinese and English, and predicts a
    space only where the gap is wide enough; a model trained on French
    would have to be downloaded, which is the one thing this program
    cannot do.

    It does not need one. Every rule in this program starts from words,
    and the words that matter are in closed lists already: a civility
    makes what follows a name, a form of company makes it a company, a
    street word makes an address, a run of digits against letters is a
    number against a word. Splitting on those recovers exactly what
    detection needs, and nothing else is touched.

    Applied to what a machine read, never to what somebody typed.
    """
    return "\n".join(
        " ".join(_split(token) for token in line.split())
        for line in text.splitlines()
    )


def _split(token: str) -> str:
    pieces = [piece for piece in _DIGIT_BOUNDARY.split(token) if piece]
    return " ".join(part for piece in pieces for part in _peel(piece))


def _peel(piece: str) -> list[str]:
    """Take known words off both ends of a run, repeatedly.

    Both ends and never the middle: ``THERMOPACKINDUSTRIE`` gives up
    ``INDUSTRIE`` from the right and leaves a name, where a search
    through the middle would cut a word that merely contains another.
    """
    folded = _fold(piece).upper()
    for word in GLUE_WORDS:
        if len(folded) <= len(word) + _MIN_REMAINDER:
            continue
        if folded.startswith(word):
            return [piece[:len(word)]] + _peel(piece[len(word):])
        if folded.endswith(word):
            cut = len(piece) - len(word)
            return _peel(piece[:cut]) + [piece[cut:]]
    return [piece]


class Unavailable(RuntimeError):
    """No engine in this build. Said plainly rather than guessed at."""


def available() -> bool:
    """Whether this build can read a scan at all.

    The engine is an optional dependency: the window runs without it,
    and says so when a scan is offered, rather than failing on an
    import three screens later.
    """
    return not diagnosis()


def diagnosis() -> str:
    """Empty when a scan can be read, and why not when it cannot.

    Worth a function of its own because the answer arrives from a
    machine nobody is sitting at. The first bundle built with the engine
    did not have it, and "absent" was all there was to go on: a missing
    package, a model file left out of the one-file archive and a native
    library that will not load all read the same from outside.
    """
    try:
        _engine()
    except Unavailable as error:
        return str(error)
    return ""


_cached = None


def _engine():
    """The recognition engine, built once.

    Imported here and not at module level: loading it costs a second or
    two and pulls in a numerical stack, and most sessions never open a
    scan. Built once because building it reads the models from disk.
    """
    global _cached
    if _cached is not None:
        return _cached
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as error:  # pragma: no cover - depends on the build
        raise Unavailable(f"paquet absent du build : {error}") from error
    try:
        _cached = RapidOCR()
    except Exception as error:  # noqa: BLE001 - any failure here means the same
        # Present and unusable: a model file the one-file archive left
        # behind, or a native library that will not load. Said as it is,
        # because the two are fixed differently and from outside they
        # look identical.
        raise Unavailable(f"moteur présent mais refuse de démarrer : {error}") from error
    return _cached


def read(source) -> Reading:
    """Read one image, from a file or from memory.

    An unreadable scan is an ordinary outcome, not an error: a blank
    page, a photograph of a desk, a page of handwriting. It comes back
    empty and the window says so.

    An array rather than a path is how a PDF page arrives: rendering it
    to a temporary file first would put a page of the client's document,
    in clear, in a folder nobody cleans.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.suffix.lower() not in IMAGES:
            raise ValueError(f"« {path.suffix} » n'est pas une image que je sais lire")
        source = str(path)

    result, _ = _engine()(source)
    if not result:
        return Reading()

    lines: list[tuple[str, float]] = []
    for item in result:
        # (box, text, score), which is what every version of this engine
        # has returned; read defensively because a shape change here
        # would otherwise surface as an exception on a user's scan.
        if len(item) < 3:
            continue
        text, score = respace(str(item[1]).strip()), _score(item[2])
        if text:
            lines.append((text, score))

    return Reading(text="\n".join(text for text, _ in lines), lines=lines)


def _score(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
