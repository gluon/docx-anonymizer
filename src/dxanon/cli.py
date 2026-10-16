"""Command line front end.

The engine is usable before the interface exists, which is the point: the
part that must be right is testable without a window.  The GUI comes
later and calls exactly these functions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import RefusedExport, anonymize, deanonymize
from .mapping import Mapping, variants


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dxanon", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    out = sub.add_parser("anonymize", help="produce an anonymised copy")
    out.add_argument("source", type=Path)
    out.add_argument("destination", type=Path)
    out.add_argument("--mapping", type=Path, required=True)

    back = sub.add_parser("restore", help="put the real values back")
    back.add_argument("source", type=Path)
    back.add_argument("destination", type=Path)
    back.add_argument("--mapping", type=Path, required=True)
    back.add_argument(
        "--allow-partial",
        action="store_true",
        help="accept a document where some pseudonyms never came back",
    )

    scan = sub.add_parser("scan", help="show what would be masked, and decide nothing")
    scan.add_argument("source", type=Path, help="a .docx or a .txt")
    scan.add_argument("--mapping", type=Path, help="write the proposed table here")

    add = sub.add_parser("add", help="declare one real value and its pseudonym")
    add.add_argument("--mapping", type=Path, required=True)
    add.add_argument("real")
    add.add_argument("pseudonym")
    add.add_argument("--kind", default="name")
    add.add_argument(
        "--with-variants",
        action="store_true",
        help="also declare the usual spellings of this name",
    )

    args = parser.parse_args(argv)

    if args.command == "add":
        return _add(args)
    if args.command == "scan":
        return _scan(args)
    return _convert(args)


def _scan(args) -> int:
    from . import workflow
    from .workflow import Decision

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

    if args.mapping:
        grid.to_mapping().save(args.mapping)
        print(f"\nTable proposée écrite dans {args.mapping}. Relisez-la avant de l'utiliser.")
    return 0


def _read_any(path: Path) -> tuple[str, list[str]]:
    if path.suffix.lower() != ".docx":
        return path.read_text(encoding="utf-8"), []
    from . import textmap
    from .package import Package

    package = Package.open(path)
    chunks = [textmap.full_text(textmap.parse(p.data)) for p in package.stories()]
    return "\n".join(c for c in chunks if c), [p.name for p in package.images()]


def _add(args) -> int:
    mapping = Mapping.load(args.mapping) if args.mapping.exists() else Mapping()
    mapping.add(args.real, args.pseudonym, kind=args.kind)
    if args.with_variants:
        real_forms = variants(args.real)
        fake_forms = variants(args.pseudonym)
        for real, fake in zip(real_forms, fake_forms):
            mapping.add(real, fake, kind=args.kind, note=f"variant of {args.real}")
    mapping.save(args.mapping)
    print(f"{len(mapping.entries)} entries in {args.mapping}")
    return 0


def _convert(args) -> int:
    mapping = Mapping.load(args.mapping)
    try:
        if args.command == "anonymize":
            report = anonymize(args.source, args.destination, mapping)
        else:
            report = deanonymize(
                args.source, args.destination, mapping, require_all=not args.allow_partial
            )
    except RefusedExport as refused:
        print("REFUSED, nothing was written:", file=sys.stderr)
        for residue in refused.residues:
            print(f"  {residue.value!r} -> {residue.where}", file=sys.stderr)
        return 2

    print(f"{report.replacements} replacement(s) in {len(report.parts_changed)} part(s)")
    for name in report.parts_changed:
        print(f"  changed {name}")
    for name in report.images:
        print(f"  IMAGE NOT PROCESSED: {name} (text inside it is not read)")
    for value in report.unresolved:
        print(f"  NOT RESTORED: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
