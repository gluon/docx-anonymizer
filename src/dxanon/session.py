"""A session: one outward trip and its return, kept on disk.

The table has to survive closing the window. A lawyer anonymises in the
morning, pastes into a chat, comes back after lunch with the corrected
text; if the real names only lived in memory, they are gone and the
document can never be restored.

Everything a session holds stays in one folder, next to the work rather
than in a hidden application directory: it is case material, it gets
backed up and deleted with the rest of the case, and nobody has to be
told where the program keeps its state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .mapping import Mapping

SCHEMA = 1
FOLDER_SUFFIX = ".dxanon"


@dataclass
class Session:
    """One piece of work, file-based or pasted."""

    folder: Path
    label: str
    mode: str  # "file" | "text"
    created: str
    mapping: Mapping = field(default_factory=Mapping)
    source_name: str = ""

    def entries_count(self) -> int:
        return len(self.mapping.entries)

    # ---------------------------------------------------------------- paths
    @property
    def mapping_path(self) -> Path:
        return self.folder / "mapping.json"

    @property
    def manifest_path(self) -> Path:
        return self.folder / "session.json"

    @property
    def anonymised_text_path(self) -> Path:
        return self.folder / "anonymised.txt"

    # --------------------------------------------------------------- create
    @classmethod
    def create(cls, parent, label: str, mode: str, source_name: str = "") -> "Session":
        parent = Path(parent)
        folder = _unique(parent / f"{_slug(label)}{FOLDER_SUFFIX}")
        folder.mkdir(parents=True)
        session = cls(
            folder=folder,
            label=label,
            mode=mode,
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source_name=source_name,
        )
        session.save()
        return session

    def save(self) -> None:
        self.mapping.save(self.mapping_path)
        self.manifest_path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "label": self.label,
                    "mode": self.mode,
                    "created": self.created,
                    "source_name": self.source_name,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, folder) -> "Session":
        folder = Path(folder)
        payload = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        if payload.get("schema") != SCHEMA:
            raise ValueError(f"unsupported session schema: {payload.get('schema')!r}")
        mapping_path = folder / "mapping.json"
        return cls(
            folder=folder,
            label=payload["label"],
            mode=payload["mode"],
            created=payload["created"],
            mapping=Mapping.load(mapping_path) if mapping_path.exists() else Mapping(),
            source_name=payload.get("source_name", ""),
        )

    def delete(self) -> list[Path]:
        """Erase the session and everything it holds. Returns what went.

        The correspondence table is the sensitive artefact of the whole
        exercise: it is the one file that maps the pseudonyms back to the
        client. When a case is done, it should be possible to remove it
        without hunting for it.

        What this does NOT claim: that the bytes are unrecoverable. On an
        SSD, wear levelling means overwriting a file in place does not
        reliably overwrite the blocks that held it, so a tool that
        scrubbed before unlinking would be selling a guarantee it cannot
        keep. This removes the files. Whole-disk encryption is what makes
        the removal meaningful, and that is said plainly in the window.
        """
        removed: list[Path] = []
        if not self.folder.exists():
            return removed
        for path in sorted(self.folder.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
                removed.append(path)
            elif path.is_dir():
                path.rmdir()
        self.folder.rmdir()
        removed.append(self.folder)
        return removed

    def outputs(self, beside: Path | None = None) -> list[Path]:
        """Files this session produced that are still on disk.

        Offered alongside deletion rather than deleted with it: an
        anonymised copy may well have been sent somewhere and be worth
        keeping, and guessing wrong in either direction is worse than
        asking. Deleting the table without these leaves files nobody can
        ever turn back, which the window says before it does it.
        """
        folder = beside or self.folder.parent
        if not self.source_name:
            return []
        stem = Path(self.source_name).stem
        found = [folder / f"{stem}_ANON.docx", folder / f"{stem}_FINAL.docx"]
        return [path for path in found if path.exists()]

    @classmethod
    def recent(cls, parent, limit: int = 20) -> list["Session"]:
        """Sessions under ``parent``, newest first, skipping broken ones."""
        found: list[Session] = []
        for folder in sorted(Path(parent).glob(f"*{FOLDER_SUFFIX}")):
            try:
                found.append(cls.load(folder))
            except Exception:
                continue  # a half-written folder must not break the list
        return sorted(found, key=lambda s: s.created, reverse=True)[:limit]


def _slug(label: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "-", label, flags=re.UNICODE).strip("-")
    return (cleaned or "session")[:60]


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find a free name near {path}")
