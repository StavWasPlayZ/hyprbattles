"""Which programs the daemon may start, where they are, and what they see.

The daemon runs for as long as the plugin is enabled and starts a handful of
other programs in the course of a battle: a player for the music, `pkill` to
sweep up an earlier daemon's players, `omarchy-toggle-bar` to hide the bar,
`notify-send` for the closing line. Looking those up on an inherited $PATH
and handing them an inherited environment meant that anything earlier on the
path, or a loader or interpreter variable somebody had managed to set in the
session, ran with the plugin the moment it was enabled. So:

  * a tool is looked for in a fixed list of system directories only, never
    on $PATH, and only taken if it is a regular, executable file owned by
    root that nobody but root can write to. Anything else is treated as not
    installed, which for every tool here means a quieter battle, not a
    broken one;
  * each is resolved once and remembered;
  * every child gets the same small environment: a fixed $PATH of those
    same directories, and a short list of session variables passed through
    by name - where the sockets are, which display, which bus. Nothing else,
    so nothing that changes how a program loads or which interpreter it
    gets is inherited.

Launcher.qml does the same for the two programs the shell itself starts,
with the same list of names; a test keeps the two lists equal.

No third-party modules.
"""

import os
import stat

# Where a tool may be. `/usr/share/omarchy/bin` is Omarchy's own, installed
# by the package manager and root's like the rest; `omarchy-toggle-bar`
# lives there and reaches for its neighbours by name, which is why it is on
# the path handed down as well as on this list.
DIRECTORIES = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/share/omarchy/bin")
PATH = ":".join(DIRECTORIES)

# The interpreter. Fixed, and told with -I to ignore every PYTHON* variable
# and the user's site directory, so what it runs is what is in the plugin.
PYTHON = "/usr/bin/python3"

# What a child is told about the session, by name. Sockets and files the
# players and the notifier need to find, and nothing that changes how a
# program is loaded: no LD_*, no PYTHON*, no PATH of anybody's but ours.
PASSED = (
    "HOME",
    "LANG",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "XDG_STATE_HOME",
    "XDG_DATA_HOME",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "HYPRBATTLES_ASSETS",
)

_found = {}


def trusted(info):
    """Whether a file with this stat is one the daemon may run: a regular
    file, executable, root's, and writable by root alone."""
    mode = info.st_mode
    return (stat.S_ISREG(mode)
            and bool(mode & stat.S_IXUSR)
            and info.st_uid == 0
            and not mode & (stat.S_IWGRP | stat.S_IWOTH))


def find(name, directories=DIRECTORIES):
    """The absolute path of `name` in the fixed directories, or None. Looked
    up once per name; $PATH is never consulted."""
    if name in _found:
        return _found[name]
    path = None
    for directory in directories:
        candidate = os.path.join(directory, name)
        try:
            info = os.stat(candidate)
        except OSError:
            continue
        if trusted(info):
            path = candidate
            break
    _found[name] = path
    return path


def forget():
    """Drop what has been found, so a test can look again."""
    _found.clear()


def environment(source=None):
    """The environment every child gets: a fixed PATH and the passed names
    that are set in `source` (the daemon's own environment by default)."""
    source = os.environ if source is None else source
    child = {"PATH": PATH}
    for name in PASSED:
        value = source.get(name)
        if value:
            child[name] = value
    return child
