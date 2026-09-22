"""Just enough of Hyprland's sockets, for the two programs that need them.

`bin/battles` listens on the event socket and asks the command socket what
windows exist; `bin/hyprbattles-ctl` needs the same command socket to move a
window when the daemon is not running. One copy, so they cannot disagree
about where the sockets are or how a reply is read.

Nothing here knows anything about battles.

No third-party modules.
"""

import itertools
import json
import os
import socket

# Hyprland's own sockets live under $XDG_RUNTIME_DIR/hypr/, and Hyprland will
# not start without one; nothing is ever created here, only connected to.
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"

# One reply, whole. Hyprland answers `j/clients` with a few hundred bytes per
# window, so this is thousands of windows' worth; a reply past it is not one
# anybody here could use, and reading it in regardless was the one way a
# window's own metadata - a title is whatever the window says it is - could
# grow the daemon and the panel without limit. Over the line the reply is
# dropped whole, not cut: a truncated JSON document is worth nothing.
REPLY_LIMIT = 4 * 1024 * 1024
# And what of a parsed reply is kept, before any of it reaches the overlay or
# the panel: this many entries in a list or keys in an object, this many
# characters in one string, and nesting this deep. The lists are windows,
# workspaces and monitors, none of which come close; the strings are titles,
# classes and commands, which are read and shown, never parsed.
MAX_ITEMS = 1024
MAX_STRING = 1024
MAX_DEPTH = 8


def bounded(value, depth=0):
    """`value` with every string cut to MAX_STRING, every list and object cut
    to MAX_ITEMS, and anything nested past MAX_DEPTH dropped. Numbers,
    booleans and null pass through."""
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, list):
        if depth >= MAX_DEPTH:
            return []
        return [bounded(item, depth + 1) for item in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        if depth >= MAX_DEPTH:
            return {}
        return {str(key)[:MAX_STRING]: bounded(item, depth + 1)
                for key, item in itertools.islice(value.items(), MAX_ITEMS)}
    return value


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
                chunks, size = [], 0
                while True:
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > REPLY_LIMIT:
                        # Nothing that size is an answer. Same as no answer.
                        return ""
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
        # RecursionError is what json makes of a document nested deeper than
        # the interpreter will go; it is as much "not an answer" as bad JSON.
        try:
            return bounded(json.loads(self.request("j/" + what)))
        except (ValueError, TypeError, RecursionError):
            return None

    def events(self):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(self.event_socket)
        return client
