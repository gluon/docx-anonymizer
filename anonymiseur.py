"""Entry point for the packaged executable.

PyInstaller runs its entry script as ``__main__`` with no package
around it, so ``src/dxanon/__main__.py`` cannot be used directly: every
``from . import`` in it raises "attempted relative import with no known
parent package". The failure is invisible in a ``--windowed`` build,
where the bootloader reports it in a message box that waits for a click
nobody is there to give, so the process never exits: the first build
hung for eighteen minutes on a runner before being cancelled.

This file exists to be that entry script. It imports the package
normally and hands over, which is also what ``python -m dxanon`` does.
"""

from dxanon.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
