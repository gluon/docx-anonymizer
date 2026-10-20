"""A case: several pieces, one table of names.

Phase one masked one document at a time, and that is the right shape for
a question asked about one document. It is the wrong shape for a case.
Masked separately, the same client is Marc Lemoine in the conclusions and
Hugo Soler in the mail thread, and an AI asked to follow an argument
across the two reads two people. The table has to be the case's, not the
document's.

That changes one rule of phase one, deliberately and only here. A
one-shot cycle kept its table in memory and wrote it nowhere, because a
table on disk outlives the work that needed it. A case is by definition
something you come back to: a piece arrives next week and has to be
masked with the names already chosen. So the table can be saved, and
everything about the file says what it holds.

What has not changed: nothing is written unless asked, nothing travels
with an exported document, and the table never sits in the folder a
masked document is written to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import engine, plaintext, source, workflow
from .engine import RefusedExport
from .mapping import Entry, Mapping
from .workflow import Grid

SCHEMA = 1

#: The first thing anyone opening the file reads, in their language.
WARNING = (
    "Ce fichier contient les vrais noms du dossier. Il ne doit pas être "
    "transmis, ni joint à un courriel, ni déposé dans un espace partagé."
)

#: Deliberately long and unmistakable. A table called "case.json" is a
#: file someone attaches by mistake; this one cannot be mistaken for the
#: masked document it belongs to.
SUFFIX = ".table-noms.json"


@dataclass
class Piece:
    """One document of the case, or one pasted text."""

    label: str
    text: str
    path: Path | None = None
    identities: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    #: The real values the masking pass actually consumed in THIS piece,
    #: and the name it was written under. Both are needed on the way
    #: back: the return trip refuses a document when a pseudonym it
    #: wrote has gone missing, and in a case most pseudonyms belong to
    #: other pieces. Checked against the whole case's table, every piece
    #: would be refused for the names it never contained.
    used: set[str] = field(default_factory=set)
    masked: Path | None = None

    @property
    def is_file(self) -> bool:
        return self.path is not None


@dataclass
class Outcome:
    """What became of one piece during an export or a restoration."""

    label: str
    written: Path | None = None
    text: str | None = None
    refused: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    used: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.refused


class Case:
    """The pieces, the grid they produced, and the table it comes from."""

    def __init__(self, name: str = "", pieces: list[Piece] | None = None) -> None:
        self.name = name
        self.pieces: list[Piece] = list(pieces or [])
        self.grid: Grid | None = None
        #: Set when the case was loaded from a saved table, or saved: the
        #: table then outranks a fresh analysis, because the pseudonyms it
        #: holds are the ones already sent out.
        self.table: Mapping | None = None

    # -- building ---------------------------------------------------------

    def add_file(self, path) -> Piece:
        path = Path(path)
        text, images, identities = source.read_document(path)
        piece = Piece(label=path.name, text=text, path=path,
                      identities=identities, images=images)
        self.pieces.append(piece)
        return piece

    def add_text(self, label: str, text: str) -> Piece:
        piece = Piece(label=label, text=text)
        self.pieces.append(piece)
        return piece

    def remove(self, label: str) -> None:
        self.pieces = [p for p in self.pieces if p.label != label]

    # -- deciding ---------------------------------------------------------

    def analyse(self) -> Grid:
        """One grid over every piece, keeping any pseudonym already chosen.

        A piece added to a case that has already been exported must not
        renumber the case. The names in the saved table win, and only
        values the table has never seen get a new pseudonym.
        """
        grid = workflow.build_many(
            [(p.label, p.text, p.identities) for p in self.pieces]
        )
        if self.table is not None:
            _reuse(grid, self.table)
        grid.images = sorted({image for p in self.pieces for image in p.images})
        self.grid = grid
        return grid

    def mapping(self) -> Mapping:
        if self.grid is None:
            raise ValueError("analyse the case before asking for its table")
        table = self.grid.to_mapping()
        if self.table is not None:
            table.used |= self.table.used
        return table

    # -- exporting --------------------------------------------------------

    def export(self, folder=None) -> list[Outcome]:
        """Mask every piece with the one table.

        A piece that is refused does not stop the others. Nothing was
        written for it, so there is nothing to undo, and a case of nine
        pieces where one holds a surviving name is a case where eight are
        ready and one needs a look. The refusal travels in its outcome.
        """
        table = self.mapping()
        self.table = table
        folder = Path(folder) if folder is not None else None
        if folder is not None:
            # Asked for a folder that does not exist yet: the masking is
            # done and the refusal check has passed by the time the file
            # is written, so failing here would throw away the work for
            # a missing directory.
            folder.mkdir(parents=True, exist_ok=True)
        outcomes: list[Outcome] = []

        for piece in self.pieces:
            outcome = Outcome(label=piece.label)
            try:
                if piece.is_file:
                    destination = (folder or piece.path.parent) / _masked_name(piece.path, table)
                    report = engine.anonymize(piece.path, destination, table)
                    piece.used, piece.masked = set(report.used), destination
                    outcome.written, outcome.used = destination, piece.used
                else:
                    outcome.text = plaintext.anonymize(piece.text, table)
                    piece.used = plaintext._applied(piece.text, table.forward())
                    outcome.used = piece.used
            except RefusedExport as refused:
                outcome.refused = sorted({r.value for r in refused.residues})
            outcomes.append(outcome)
        return outcomes

    def restore_file(self, path, destination=None, label: str | None = None) -> Outcome:
        path = Path(path)
        table, strict = self._table_for(label, path)
        destination = Path(destination) if destination is not None else (
            path.with_name(f"{path.stem.replace('_ANON', '')}_FINAL{path.suffix}")
        )
        outcome = Outcome(label=label or path.name)
        try:
            report = engine.deanonymize(path, destination, table, require_all=strict)
            outcome.written, outcome.unresolved = destination, report.unresolved
        except RefusedExport as refused:
            outcome.refused = sorted({r.value for r in refused.residues})
        return outcome

    def restore_text(self, text: str, label: str | None = None) -> Outcome:
        table, strict = self._table_for(label, None)
        outcome = Outcome(label=label or "texte")
        try:
            restored, missing = plaintext.deanonymize(text, table, require_all=strict)
            outcome.text, outcome.unresolved = restored, missing
        except RefusedExport as refused:
            outcome.refused = sorted({r.value for r in refused.residues})
        return outcome

    def _table_for(self, label: str | None, path: Path | None) -> tuple[Mapping, bool]:
        """The table to restore one piece with, and whether to be strict.

        The return trip's real failure is a pseudonym the model reworded:
        it matches nothing, is never restored, and can only be seen as an
        absence. So a missing pseudonym stops the restoration.

        In a case that check has to be asked piece by piece. The table
        belongs to the whole case, so most of its pseudonyms are not in
        the document being restored and never were: checked against the
        case, every piece would be refused for names it never contained.
        Each piece therefore carries what the masking pass consumed in
        it, and that is what is demanded of it.

        A piece nobody can identify falls back to reporting rather than
        refusing. Refusing would be refusing on a question that was not
        asked; the unresolved pseudonyms travel in the outcome instead,
        for the window to show.
        """
        table = self.table or self.mapping()
        piece = self._piece_for(label, path)
        if piece is None or not piece.used:
            return table, False
        return Mapping(entries=table.entries, used=set(piece.used)), True

    def _piece_for(self, label: str | None, path: Path | None) -> Piece | None:
        if label is not None:
            return next((p for p in self.pieces if p.label == label), None)
        if path is None:
            return self.pieces[0] if len(self.pieces) == 1 else None
        # Matched on the name the masking pass wrote, which is the name
        # the user is handing back, possibly from another folder.
        by_name = [p for p in self.pieces if p.masked and p.masked.name == path.name]
        return by_name[0] if len(by_name) == 1 else None

    # -- coming back ------------------------------------------------------

    def save(self, path) -> Path:
        """Write the table, and only the table.

        The pieces are recorded by name and location, never by content: a
        case file holding the text of every document would be a second
        copy of the case, in a format nobody expects to be confidential.

        ``used`` is part of what is written. Without it a reloaded table
        treats every entry as one that fired, and the return trip then
        refuses a perfectly good document over a pseudonym it never
        wrote.
        """
        table = self.table or self.mapping()
        path = Path(path)
        payload = {
            "avertissement": WARNING,
            "schema": SCHEMA,
            "dossier": self.name,
            "pieces": [
                {"label": p.label, "fichier": str(p.path) if p.path else None}
                for p in self.pieces
            ],
            "table": [
                {"reel": e.real, "pseudonyme": e.pseudonym, "nature": e.kind}
                for e in table.entries
            ],
            "appliques": sorted(table.used),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.table = table
        return path

    @classmethod
    def load(cls, path) -> Case:
        """Read a saved table back, without reading the documents.

        The pieces come back as names, not as text: whether a document is
        still where it was is not this file's business, and a case whose
        file has moved must still be able to restore what was already
        sent out.
        """
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA:
            raise ValueError(f"table de noms de schéma inconnu : {payload.get('schema')!r}")

        case = cls(name=payload.get("dossier", ""))
        case.table = Mapping(
            entries=[
                Entry(real=row["reel"], pseudonym=row["pseudonyme"],
                      kind=row.get("nature", "name"))
                for row in payload.get("table", [])
            ],
            used=set(payload.get("appliques", ())),
        )
        for record in payload.get("pieces", []):
            case.pieces.append(Piece(
                label=record["label"], text="",
                path=Path(record["fichier"]) if record.get("fichier") else None,
            ))
        return case

    def reread(self) -> list[str]:
        """Load the text of the pieces that are still on disk.

        Returns the labels of those that are not, so the window can say
        so rather than present an empty grid.
        """
        missing: list[str] = []
        for piece in self.pieces:
            if piece.path is None or piece.text:
                continue
            if not piece.path.exists():
                missing.append(piece.label)
                continue
            piece.text, piece.images, piece.identities = source.read_document(piece.path)
        return missing


def _reuse(grid: Grid, table: Mapping) -> None:
    """Give back to each row the pseudonym the table already holds."""
    for row in grid.rows:
        entry = table.for_real(row.value)
        if entry is not None:
            row.pseudonym = entry.pseudonym


def _masked_name(path: Path, table: Mapping) -> str:
    """The masked document's own name, with the names taken out of it.

    A file called ``Conclusions_Lenoir.docx`` says who the case is about
    before anyone opens it.

    Substituted by the engine's own single pass, not by chaining
    ``str.replace`` over the pairs: chaining lets a replacement be
    replaced again, which renamed a file twice and quietly produced a
    name no table could undo.
    """
    stem = engine._replace_all(path.stem, table.forward())
    return f"{stem}_ANON{path.suffix}"
