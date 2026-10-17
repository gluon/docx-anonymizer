"""Command line front end.

The engine is usable before the interface exists, which is the point:
the part that must be right is testable without a window, and the window
calls exactly these functions.

Like the window, this writes no correspondence table. A cycle is one
invocation: the table is built, used both ways, and dropped. That makes
`anonymize` and `restore` separate commands impossible, which is the
honest consequence of the design rather than an oversight: there is
nothing to carry between two runs of a program that stores nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import plaintext, workflow
from .engine import RefusedExport, anonymize, deanonymize
from .workflow import Decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dxanon", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="show what would be masked, and decide nothing")
    scan.add_argument("source", type=Path, help="a .docx or a .txt")

    mask = sub.add_parser(
        "mask",
        help="mask a copy and print the table, for a cycle you drive yourself",
    )
    mask.add_argument("source", type=Path)
    mask.add_argument("destination", type=Path)

    check = sub.add_parser(
        "roundtrip",
        help="mask and restore in one go, to prove a document survives the trip",
    )
    check.add_argument("source", type=Path)
    check.add_argument("destination", type=Path, nargs="?")

    args = parser.parse_args(argv)
    if args.command == "scan":
        return _scan(args)
    if args.command == "mask":
        return _mask(args)
    return _roundtrip(args)


def _scan(args) -> int:
    text, images = _read_any(args.source)
    grid = workflow.build(text, images=images)

    width = max((len(r.value) for r in grid.rows), default=10)
    for row in grid.rows:
        mark = "masquer " if row.decision is Decision.REPLACE else "conserver"
        arrow = f" -> {row.pseudonym}" if row.pseudonym else ""
        print(f"  [{mark}] {row.value:<{width}}  x{row.occurrences:<3d}{arrow}")
        print(f"             {row.why}")

    print(f"\n{len(grid.rows)} ligne(s) à trancher")
    for name in grid.images:
        print(f"  IMAGE NON TRAITÉE : {name} (le texte qu'elle contient n'est pas lu)")
    for problem in grid.conflicts():
        print(f"  CONFLIT : {problem}")
    return 0


def _mask(args) -> int:
    """Mask, and print the table to standard output.

    Printed rather than saved, deliberately. Whoever runs this decides
    where it goes, and a terminal that is closed takes it with it. The
    warning is there because the alternative is someone piping it into a
    file next to the document it unmasks.
    """
    text, images = _read_any(args.source)
    grid = workflow.build(text, images=images)
    mapping = grid.to_mapping()

    conflicts = grid.conflicts()
    if conflicts:
        for problem in conflicts:
            print(f"CONFLIT : {problem}", file=sys.stderr)
        return 2

    try:
        if args.source.suffix.lower() == ".docx":
            report = anonymize(args.source, args.destination, mapping)
            for name in report.images:
                print(f"  IMAGE NON TRAITÉE : {name}", file=sys.stderr)
        else:
            args.destination.write_text(plaintext.anonymize(text, mapping), encoding="utf-8")
    except RefusedExport as refused:
        print("REFUSÉ, rien n'a été écrit :", file=sys.stderr)
        for residue in refused.residues:
            print(f"  {residue.value!r} -> {residue.where}", file=sys.stderr)
        return 2

    print(f"# {args.destination}")
    print("# Table de correspondance. Elle n'est enregistrée nulle part :")
    print("# sans elle, le document masqué ne peut plus être restauré.")
    for entry in mapping.entries:
        print(f"{entry.pseudonym}\t{entry.real}")
    return 0


def _roundtrip(args) -> int:
    """Mask and restore in one invocation, and say whether anything moved."""
    text, images = _read_any(args.source)
    mapping = workflow.build(text, images=images).to_mapping()
    destination = args.destination or args.source.with_name(f"{args.source.stem}_ANON{args.source.suffix}")

    try:
        if args.source.suffix.lower() == ".docx":
            anonymize(args.source, destination, mapping)
            restored = destination.with_name(f"{args.source.stem}_FINAL.docx")
            deanonymize(destination, restored, mapping, require_all=False)
            same = _read_any(args.source)[0] == _read_any(restored)[0]
        else:
            masked = plaintext.anonymize(text, mapping)
            destination.write_text(masked, encoding="utf-8")
            back, _ = plaintext.deanonymize(masked, mapping, require_all=False)
            same = back == text
    except RefusedExport as refused:
        print("REFUSÉ, rien n'a été écrit :", file=sys.stderr)
        for residue in refused.residues:
            print(f"  {residue.value!r} -> {residue.where}", file=sys.stderr)
        return 2

    print(f"{len(mapping.entries)} correspondance(s)")
    print("aller-retour exact :", "oui" if same else "NON")
    return 0 if same else 1


def _read_any(path: Path) -> tuple[str, list[str]]:
    if path.suffix.lower() != ".docx":
        return path.read_text(encoding="utf-8"), []
    from . import textmap
    from .package import Package

    package = Package.open(path)
    chunks = [textmap.full_text(textmap.parse(p.data)) for p in package.stories()]
    return "\n".join(c for c in chunks if c), [p.name for p in package.images()]


if __name__ == "__main__":
    raise SystemExit(main())
