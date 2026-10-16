"""Entry point for the packaged executable.

``--self-check`` runs the engine end to end on a document built in
memory and exits. It exists for the Windows build: a one-file bundle
fails by missing a hidden import, and that only shows up at runtime, on
the user's machine, as a window that does not open. Running the check in
CI moves that failure to where someone can see it.
"""

from __future__ import annotations

import sys


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


def self_check() -> int:
    """Exercise every layer the bundle needs, then say so."""
    import tempfile

    from . import plaintext, workflow
    from .mapping import Mapping
    from .netguard import NetworkGuard
    from .session import Session

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

    with tempfile.TemporaryDirectory() as folder:
        session = Session.create(folder, "auto-test", mode="text")
        session.mapping = Mapping(mapping.entries)
        session.save()
        if not Session.load(session.folder).entries_count():
            say("ÉCHEC : la session ne se recharge pas", error=True)
            return 1

    say(f"OK : {len(grid.rows)} élément(s) détecté(s), aller-retour exact, "
        f"garde-fou réseau actif, {len(missing)} pseudonyme(s) non restitué(s)")
    return 0


def main() -> int:
    if "--self-check" in sys.argv:
        return self_check()
    from .gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
