"""Entry point for the packaged executable.

``--self-check`` runs the engine end to end on a document built in
memory and exits. It exists for the Windows build: a one-file bundle
fails by missing a hidden import, and that only shows up at runtime, on
the user's machine, as a window that does not open. Running the check in
CI moves that failure to where someone can see it.
"""

from __future__ import annotations

import sys


#: Where to write the report, when asked. A ``--windowed`` build has no
#: standard output at all: not a closed one, not a redirected one, None.
#: Redirecting it to a file in the shell gives an empty file, and a
#: check that read that file concluded the bundle had no recognition
#: engine when the question had simply never been asked. The report goes
#: where the caller says, through an ordinary file.
_report: object | None = None


def say(message: str, error: bool = False) -> None:
    """Print without assuming there is anywhere to print to.

    A PyInstaller ``--windowed`` build has no console: ``sys.stdout`` and
    ``sys.stderr`` are None, and a bare ``print`` raises AttributeError.
    The self-check would then fail for the one reason it is not meant to
    test, and the exit code would say the bundle is broken when it is
    fine.
    """
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream)
    if _report is not None:
        _report.write(message + "\n")
        _report.flush()


def self_check() -> int:
    """Exercise every layer the bundle needs, then say so."""
    from . import plaintext, workflow
    from .netguard import NetworkGuard

    guard = NetworkGuard.install()

    text = "Monsieur Jean DUPONT, SAS Mecanique, IBAN FR1420041010050500013M02606."
    grid = workflow.build(text)
    mapping = grid.to_mapping()
    masked = plaintext.anonymize(text, mapping)
    restored, missing = plaintext.deanonymize(masked, mapping)

    if restored != text:
        say("ÉCHEC : le texte restauré diffère de l'original", error=True)
        return 1
    if "DUPONT" in masked:
        say("ÉCHEC : une valeur réelle subsiste dans le texte masqué", error=True)
        return 1
    if not guard.installed:
        say("ÉCHEC : le garde-fou réseau n'est pas installé", error=True)
        return 1

    # Whether the recognition engine made it into the bundle. Not a
    # failure if it did not: the build without it is a working program.
    # But a one-file bundle that silently drops a package it was given
    # is exactly what this check exists to catch, and that failure would
    # otherwise surface as "cette version ne sait pas lire les images"
    # on the machine of someone who was told it could.
    from . import ocr

    trouble = ocr.diagnosis()
    say(f"OK : {len(grid.rows)} élément(s) détecté(s), aller-retour exact, "
        f"garde-fou réseau actif, {len(missing)} pseudonyme(s) non restitué(s), "
        f"lecture d'images {'incluse' if not trouble else 'absente : ' + trouble}")
    return 0


def _report_path(argv: list[str]) -> str | None:
    """``--report <file>``, or None."""
    if "--report" not in argv:
        return None
    index = argv.index("--report")
    return argv[index + 1] if index + 1 < len(argv) else None


def main(argv: list[str] | None = None) -> int:
    global _report
    argv = list(sys.argv if argv is None else argv)
    if "--self-check" in argv:
        path = _report_path(argv)
        if path is None:
            return self_check()
        with open(path, "w", encoding="utf-8") as handle:
            _report = handle
            try:
                return self_check()
            finally:
                _report = None
    from .gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
