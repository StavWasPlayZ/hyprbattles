"""Where the daemon's runtime files live, and how they are made.

The state file the overlay watches and the control socket the CLI talks to
belong in $XDG_RUNTIME_DIR, which a login session provides as a private,
per-user, 0700 directory. Without one - a session started by hand, a test
harness, a container - the old fallback was /tmp, which everybody on the
machine can write to: a predictable name there lets another account plant a
symlink where the daemon is about to write, and have the daemon truncate
whatever it points at. So the fallback is a directory of this user's own
under $XDG_STATE_HOME, made 0700, and nothing is written through a plain
path anyway: the directory is opened once and checked to be a real directory
owned by this user that nobody else may write to, and every file is created
relative to that descriptor, exclusively, without following a link, and
readable by nobody else.

Battle.qml computes the same fallback path, so the overlay finds the file
with or without a runtime directory. Keep the two in step.

No third-party modules.
"""

import errno
import os
import stat

STATE_HOME = (os.environ.get("XDG_STATE_HOME")
              or os.path.expanduser("~/.local/state"))

FALLBACK_DIR = os.path.join(STATE_HOME, "hyprscroll2d", "run")


def runtime_dir():
    """$XDG_RUNTIME_DIR, or this user's own fallback under $XDG_STATE_HOME.
    Never a shared directory."""
    return os.environ.get("XDG_RUNTIME_DIR") or FALLBACK_DIR


def open_private(path):
    """Open `path` as a directory this user owns and nobody else may write to,
    creating it 0700 when it is missing, and return the descriptor.

    Raises OSError otherwise. A symlink in its place is refused rather than
    followed, which is the whole point of doing this once with a descriptor
    instead of trusting the path on every write.
    """
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except FileNotFoundError:
        # The parent is missing too: the state directory on a fresh
        # machine. Made the same way the ledgers make it, then the leaf
        # again with its own mode.
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.mkdir(path, 0o700)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise OSError(errno.ENOTDIR, "not a directory", path)
        if info.st_uid != os.getuid():
            raise OSError(errno.EPERM, "not this user's directory", path)
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise OSError(errno.EPERM, "writable by others", path)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def write(directory, name, text):
    """Write `text` to `name` inside the opened directory, atomically.

    A temporary next to it is created exclusively - it must not exist, and a
    link left in its place is not followed - with mode 0600, filled, and
    renamed over the real name. The rename replaces whatever is there,
    a link included, and never what a link points at. The temporary has a
    fixed name so a crash leaves at most one behind; it is removed first,
    as a name, not as what it might point to.
    """
    temporary = name + ".tmp"
    try:
        os.unlink(temporary, dir_fd=directory)
    except FileNotFoundError:
        pass
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
             | os.O_CLOEXEC)
    descriptor = os.open(temporary, flags, 0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=directory)
        except OSError:
            pass
        raise
    os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)


def read(directory, name):
    """The text of `name` inside the opened directory. A link is refused."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(name, flags, dir_fd=directory)
    with os.fdopen(descriptor, "r") as handle:
        return handle.read()


def remove(directory, name):
    """Remove `name` from the opened directory if it is there. A link is
    removed as a link."""
    try:
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        pass
