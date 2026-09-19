"""Just enough of Hyprland's sockets, for the two programs that need them.

`bin/battles` listens on the event socket and asks the command socket what
windows exist; `bin/hyprbattles-ctl` needs the same command socket to move a
window when the daemon is not running. One copy, so they cannot disagree
about where the sockets are or how a reply is read.

Nothing here knows anything about battles.

No third-party modules.
"""

import json
import os
import socket

RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"


class Hyprland:
    """Just enough of Hyprland's sockets: ask it things, tell it things, and
    listen to what it announces."""

    def __init__(self):
        self.signature = (os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
                          or self._discover())
        base = os.path.join(RUNTIME_DIR, "hypr", self.signature or "")
        self.command_socket = os.path.join(base, ".socket.sock")
        self.event_socket = os.path.join(base, ".socket2.sock")

    @staticmethod
    def _discover():
        root = os.path.join(RUNTIME_DIR, "hypr")
        try:
            candidates = [
                entry for entry in os.listdir(root)
                if os.path.exists(os.path.join(root, entry, ".socket.sock"))
            ]
        except OSError:
            return None
        return candidates[0] if len(candidates) == 1 else None

    def request(self, payload):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.0)
                client.connect(self.command_socket)
                client.sendall(payload.encode())
                chunks = []
                while True:
                    chunk = client.recv(8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
            return b"".join(chunks).decode(errors="replace")
        except OSError:
            return ""

    def dispatch(self, command):
        # This Hyprland is configured in Lua and evaluates `hl.dispatch(<what
        # we sent>)`, so a classic dispatcher string is a syntax error that
        # comes back in a reply nobody reads. Everything sent from here is an
        # hl.dsp expression.
        return self.request("/dispatch " + command) if command else ""

    def query(self, what):
        try:
            return json.loads(self.request("j/" + what))
        except (ValueError, TypeError):
            return None

    def events(self):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(self.event_socket)
        return client
