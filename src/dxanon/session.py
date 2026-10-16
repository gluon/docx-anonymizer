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
