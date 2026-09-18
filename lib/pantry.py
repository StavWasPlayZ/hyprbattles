"""The pantry: what a machine has lying around that a creature can eat.

Apps are creatures, so apps are not food. What is left is the stuff every
Linux desktop has going spare - free memory, page cache, swap, entropy, dead
processes - and that turns out to be a better joke anyway: open a browser and
your creatures go hungry.

Everything here is **read-only**. It reads counters and sizes out of `/proc`
and one `statvfs`, and it does nothing else: nothing is deleted, nothing is
dropped, no cache is flushed, no process is signalled, no file contents are
read and nothing needs root. The machine is in exactly the same state after a
feast as it was before it.

Which raises the obvious question: if eating changes nothing, what stops you
feeding the same 512 MiB to a creature forever?

The ledger. A portion that has been eaten is written down with the time it was
taken, and the pantry subtracts what is still outstanding from the live
reading. So a portion is unavailable *to the game* for a while even though the
machine never lost it - and it comes back gradually, the way the resource
itself would. The fiction is honest in both directions: you cannot eat what
the machine does not have, and you cannot eat the same thing twice.
"""

import json
import os
import time

# How long an eaten portion takes to come back. Long enough that a battle
# cannot live on one item, short enough that a later battle finds a full
# pantry. Portions regenerate smoothly rather than all at once.
REGEN_SECONDS = 240.0

KIB = 1024.0
MIB = 1024.0 * 1024.0


# ------------------------------------------------------------------ readings

def read_meminfo(path="/proc/meminfo"):
    """`/proc/meminfo` as a dict of kB. Counters only; no contents of
    anything."""
    values = {}
    try:
        with open(path) as handle:
            for line in handle:
                name, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    try:
                        values[name] = float(parts[0])
                    except ValueError:
                        continue
    except OSError:
        return {}
    return values


def read_entropy(path="/proc/sys/kernel/random/entropy_avail"):
    """Bits in the kernel's entropy pool. Reading this does not drain it."""
    try:
        with open(path) as handle:
            return float(handle.read().strip())
    except (OSError, ValueError):
        return 0.0


def count_zombies(proc="/proc"):
    """Processes in state Z: finished, but not yet reaped by their parent.

    Only the state field of `/proc/<pid>/stat` is looked at, and nothing is
    signalled. A zombie holds nothing but a process table entry, which is
    what makes it such good carrion.
    """
    total = 0
    try:
        entries = os.listdir(proc)
    except OSError:
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc, entry, "stat")) as handle:
                stat = handle.read()
        except OSError:
            continue
        # The comm field is parenthesised and may contain spaces, so the
        # state is the first field after the last close parenthesis.
        tail = stat[stat.rfind(")") + 1:].split()
        if tail and tail[0] == "Z":
            total += 1
    return total


def used_bytes(path="/tmp"):
    """How much is sitting in a filesystem, from statvfs. No directory is
    walked and no file is opened, so nothing private is touched."""
    try:
        stats = os.statvfs(path)
    except OSError:
        return 0.0
    return (stats.f_blocks - stats.f_bfree) * stats.f_frsize


# --------------------------------------------------------------- the shelves
#
# Each shelf says where its reading comes from, how big one portion is, and
# what eating it does. The effects are deliberately uneven: the staple is
# dependable, the junk is strong and costs you, and the candy is a gamble.
#
# `heal` is a fraction of the creature's own maximum HP, so a big window and a
# small one both get a meal that means something.

SHELVES = (
    {
        "key": "staple",
        "name": "FREE RAM",
        "note": "Plain, filling, and gone the moment a browser opens.",
        "unit": "MiB",
        "portion": 512.0,
        "kind": "plain",
        "heal": 0.30,
        "nourish": 34,
        "reading": lambda roots: (read_meminfo(roots["meminfo"])
                                  .get("MemAvailable", 0.0) * KIB / MIB),
    },
    {
        "key": "leftovers",
        "name": "PAGE CACHE",
        "note": "Yesterday's reads, still warm. Cheap and not very filling.",
        "unit": "MiB",
        "portion": 1024.0,
        "kind": "plain",
        "heal": 0.12,
        "nourish": 12,
        "reading": lambda roots: (read_meminfo(roots["meminfo"])
                                  .get("Cached", 0.0) * KIB / MIB),
    },
    {
        "key": "junk",
        "name": "SWAP",
        "note": "Enormously filling. Sits heavy, and slows you right down.",
        "unit": "MiB",
        "portion": 256.0,
        "kind": "junk",
        "heal": 0.48,
        "nourish": 40,
        # Swapping is slow, so eating it is too.
        "penalty": {"stat": "speed", "fraction": 0.30},
        "reading": lambda roots: (
            max(0.0, read_meminfo(roots["meminfo"]).get("SwapTotal", 0.0)
                - read_meminfo(roots["meminfo"]).get("SwapFree", 0.0))
            * KIB / MIB),
    },
    {
        "key": "candy",
        "name": "ENTROPY",
        "note": "Pure randomness. Nobody knows what it does until it is eaten.",
        "unit": "bits",
        "portion": 64.0,
        "kind": "candy",
        "heal": 0.20,
        "nourish": 18,
        "reading": lambda roots: read_entropy(roots["entropy"]),
    },
    {
        "key": "carrion",
        "name": "ZOMBIES",
        "note": "Processes nobody reaped. Grim, rare, and very good for you.",
        "unit": "",
        "portion": 1.0,
        "kind": "carrion",
        "heal": 0.35,
        "nourish": 30,
        # Eating the dead is bracing.
        "boon": {"stat": "attack", "fraction": 0.15},
        "reading": lambda roots: float(count_zombies(roots["proc"])),
    },
    {
        "key": "scraps",
        "name": "TMP SCRAPS",
        "note": "Whatever the last hour left in /tmp. Barely a mouthful.",
        "unit": "MiB",
        "portion": 256.0,
        "kind": "plain",
        "heal": 0.09,
        "nourish": 9,
        "reading": lambda roots: used_bytes(roots["tmp"]) / MIB,
    },
)

DEFAULT_ROOTS = {
    "meminfo": "/proc/meminfo",
    "entropy": "/proc/sys/kernel/random/entropy_avail",
    "proc": "/proc",
    "tmp": "/tmp",
}

BY_KEY = {shelf["key"]: shelf for shelf in SHELVES}


# ------------------------------------------------------------------- ledger

class Ledger:
    """What has been eaten lately, and how much of it has grown back.

    Portions regenerate linearly over REGEN_SECONDS. Wall-clock time is used
    rather than a monotonic one on purpose: the ledger is written to disk and
    has to keep meaning something across a shell restart.
    """

    def __init__(self, path=None):
        self.path = path
        self.entries = []
        self.load()

    def load(self):
        if not self.path:
            return
        try:
            with open(self.path) as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return
        for entry in entries:
            try:
                self.entries.append({"key": str(entry["key"]),
                                     "amount": float(entry["amount"]),
                                     "at": float(entry["at"])})
            except (KeyError, TypeError, ValueError):
                continue

    def save(self):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w") as handle:
                json.dump({"entries": self.entries}, handle)
            os.replace(temporary, self.path)
        except OSError:
            pass            # a ledger we cannot save is not worth a crash

    @staticmethod
    def remaining(entry, now):
        """How much of one portion has not grown back yet, 1.0 down to 0.0."""
        age = now - entry["at"]
        if age <= 0:
            return 1.0      # clock went backwards; treat it as just eaten
        if age >= REGEN_SECONDS:
            return 0.0
        return 1.0 - age / REGEN_SECONDS

    def prune(self, now):
        self.entries = [entry for entry in self.entries
                        if self.remaining(entry, now) > 0.0]

    def outstanding(self, key, now):
        """How much of `key` is still spoken for."""
        return sum(entry["amount"] * self.remaining(entry, now)
                   for entry in self.entries if entry["key"] == key)

    def take(self, key, amount, now):
        self.prune(now)
        self.entries.append({"key": key, "amount": float(amount),
                             "at": float(now)})
        self.save()

    def clear(self):
        self.entries = []
        self.save()


# ------------------------------------------------------------------ pantry

class Pantry:
    """The live readings, minus what is still owed to the ledger."""

    def __init__(self, ledger=None, roots=None, clock=time.time):
        self.ledger = ledger if ledger is not None else Ledger()
        self.roots = dict(DEFAULT_ROOTS, **(roots or {}))
        self.clock = clock

    # The `now` these three take is the caller's battle clock, which is a
    # monotonic one - it counts from an arbitrary zero and restarts at boot.
    # The ledger is written to disk and has to survive a reboot, so it keeps
    # wall-clock time and the pantry uses its own clock throughout. Taking the
    # caller's number instead would write a monotonic timestamp into a
    # wall-clock ledger, and after a reboot every entry would look like it was
    # eaten in the future and never grow back.
    def available(self, shelf, _now=None):
        now = self.clock()
        try:
            reading = float(shelf["reading"](self.roots))
        except Exception:
            # A reading that is not there is an empty shelf, never a crash.
            return 0.0
        return max(0.0, reading - self.ledger.outstanding(shelf["key"], now))

    def stock(self, _now=None):
        """Every shelf, with what is on it right now.

        `servings` is how many whole portions are there; a shelf with none is
        still listed, because an empty shelf is part of the joke.
        """
        now = self.clock()
        self.ledger.prune(now)
        shelves = []
        for shelf in SHELVES:
            available = self.available(shelf, now)
            portion = shelf["portion"]
            shelves.append({
                "key": shelf["key"],
                "name": shelf["name"],
                "note": shelf["note"],
                "unit": shelf["unit"],
                "kind": shelf["kind"],
                "portion": portion,
                "available": available,
                "servings": int(available // portion) if portion > 0 else 0,
                "heal": shelf["heal"],
                "nourish": shelf["nourish"],
                "penalty": shelf.get("penalty"),
                "boon": shelf.get("boon"),
            })
        return shelves

    def take(self, key, _now=None):
        """Eat one portion. Returns the serving, or None if the shelf is bare.

        This writes to the ledger and to nothing else. No kernel state is
        touched here or anywhere in this module.
        """
        now = self.clock()
        shelf = BY_KEY.get(key)
        if not shelf:
            return None
        available = self.available(shelf, now)
        if available < shelf["portion"]:
            return None
        self.ledger.take(key, shelf["portion"], now)
        serving = dict(shelf)
        serving.pop("reading", None)
        serving["available"] = available - shelf["portion"]
        return serving


def describe(amount, unit):
    """A reading as something short enough for a menu row."""
    if unit == "MiB":
        if amount >= 1024:
            return "%.1f GiB" % (amount / 1024.0)
        return "%d MiB" % int(amount)
    if unit:
        return "%d %s" % (int(amount), unit)
    return "%d" % int(amount)
