"""Making "nothing leaves this machine" checkable rather than promised.

A lawyer cannot audit the source, and "it does not connect to anything"
is exactly the kind of claim a tool should not ask to be taken on faith.
So the program blocks its own outbound connections and shows, in the
window, whether any were attempted. Green means the guard is installed
and nothing tried to leave; a count means something did, and that is
worth knowing whatever caused it.

This is a safety net over an honest program, not a sandbox. It runs
inside the process, so it constrains mistakes and dependencies rather
than a determined attacker, who would simply not use it. The real
guarantee is that the source is public and has no network code in it;
this makes the absence visible to someone who cannot read the source.

Loopback is allowed and counted separately: blocking it outright risks
breaking toolkits that use a local socket for their own plumbing, and a
connection to 127.0.0.1 does not leave the machine anyway.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field


@dataclass
class NetworkGuard:
    attempts: list[str] = field(default_factory=list)
    loopback: list[str] = field(default_factory=list)
    installed: bool = False
    #: The real socket methods, kept so a test can put them back.
    _restore: tuple | None = None

    @property
    def clean(self) -> bool:
        """True when nothing has tried to reach beyond this machine."""
        return not self.attempts

    @classmethod
    def install(cls) -> "NetworkGuard":
        guard = cls()
        original = socket.socket.connect
        original_ex = socket.socket.connect_ex

        def blocked(self, address, *args, **kwargs):  # noqa: ANN001
            host = _host_of(address)
            if _is_local(host):
                guard.loopback.append(str(host))
                return original(self, address, *args, **kwargs)
            guard.attempts.append(str(host))
            raise OSError(
                f"connexion réseau bloquée vers {host} : ce programme fonctionne hors ligne"
            )

        def blocked_ex(self, address, *args, **kwargs):  # noqa: ANN001
            host = _host_of(address)
            if _is_local(host):
                return original_ex(self, address, *args, **kwargs)
            guard.attempts.append(str(host))
            return 1  # a non-zero errno, which is how connect_ex reports failure

        socket.socket.connect = blocked
        socket.socket.connect_ex = blocked_ex
        guard.installed = True
        guard._restore = (original, original_ex)
        return guard

    def uninstall(self) -> None:
        """Put the real socket back.

        The program never calls this: the guard is installed for the
        life of the window. A test does, having installed a guard of its
        own to prove that some dependency opens nothing, and a test that
        left the patch in place would hand its replacement to every test
        that followed.
        """
        if self._restore is None:
            return
        socket.socket.connect, socket.socket.connect_ex = self._restore
        self._restore = None
        self.installed = False


def _host_of(address) -> object:
    if isinstance(address, tuple) and address:
        return address[0]
    return address


def _is_local(host) -> bool:
    if not isinstance(host, str):
        # AF_UNIX and friends: a path, not a network address.
        return True
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname that has to be resolved is, by definition, not local.
        return False
