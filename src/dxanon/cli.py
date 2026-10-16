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
    return _convert(args)


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
