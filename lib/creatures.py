"""What a window remembers between fights, and how much it can still eat.

`lib/battle_rules.py` decides what a level *means*; this decides what carries
it. The two questions it answers are deliberately different:

**Who is this creature?** Its class - `initialClass`, the name the window was
launched under. Not its address: Hyprland addresses die with the window and
are handed out again later, so a record kept under one would be lost every
time you restarted Firefox and then inherited by whatever opened next. A
class is the only handle a window has that survives its own death, so your
browser is the same creature tomorrow as it was today.

That means every window of a class shares one record. Two terminals are the
same creature twice, the way two of the same monster are. Feeding one feeds
"terminals", and that is the honest reading of a class-keyed identity.

**How much can it eat?** That one *is* per window, and it is bought with
uptime: a window that has been open all day has an appetite, a window opened
a minute ago has almost none. Uptime comes from `/proc/<pid>/stat`, not from
anything this daemon wrote down, so it survives a daemon restart and cannot
be farmed by reopening the panel.

**And what is it running?** A terminal with Claude Code or Codex in it is an
agent rather than a terminal, and neither its class nor its title says so -
the class is `foot` and the title is the name of your work. So the process
tree under the window is walked instead (`agent_of`), which is the same rule
every other number here follows: a reading of something real.

Reading here is read-only in the same sense `lib/pantry.py` is - counters,
`comm` and `cmdline` out of `/proc`, nothing a `ps` would not print - but
this module does write, to its own file and nowhere else:
`~/.local/state/hyprscroll2d/creatures.json`.
"""

import json
import os
import time

STATE_HOME = (os.environ.get("XDG_STATE_HOME")
              or os.path.expanduser("~/.local/state"))
STORE_PATH = os.path.join(STATE_HOME, "hyprscroll2d", "creatures.json")

# An appetite entry is worth keeping only while its window is alive. They are
# tiny, so the file is swept on save rather than on every read.
MAX_APPETITE_ENTRIES = 400


def species_key(window, proc="/proc"):
    """The name a creature is remembered under: its launch class, folded.

    One answer, in the rules, because the same key is what its stats are hung
    off; `class` is the fallback for the same reason `display_name` prefers
    the initial one - a browser that renames itself after the site it is
    showing must not become a different creature halfway through the
    afternoon.

    The exception is an agent, which has no class of its own because it is
    not a window - so the window is asked what it is *running* first (see
    `agent_of`), and the answer is written onto the window dict as `agent`.
    The rules are pure and cannot go looking; stamping it here means every
    question that follows - the record, the type, the name, the stats - is
    asked of the same window and gets the same answer. This is the choke
    point on purpose: everything that turns a window into a creature comes
    through a record first.
    """
    if isinstance(window, dict) and "agent" not in window:
        window["agent"] = agent_in_window(window, proc)
    return rules.species_key(window)


# This plugin's own windows are not creatures. Nothing it draws is a client
# today - the overlay and the panel are both layer surfaces - but anything it
# ever does put on screen is scaffolding for the game, and scaffolding that
# fights, eats and sleeps is the game reading itself. The same rule the
# pantry follows: a number has to be a reading of something real, and a
# window this plugin opened is a reading of this plugin.
OUR_NAME = "hyprbattles"


def ours(key):
    """Is this class one of ours? A substring, not a prefix: the plugin's
    own id is reverse-DNS (`dev.cstav.omarchy.plugin.hyprbattles`) and
    anything it spawns is named after it at one end or the other."""
    return OUR_NAME in str(key or "").strip().lower()


def sleeping_window(key):
    """A window dict for a creature whose window is closed. It has a class,
    which is all a creature ever really was, and no address, no pid and no
    size - so it has no appetite and cannot be fed."""
    return {"initialClass": str(key or "window"), "address": "",
            "class": str(key or "window")}


# ------------------------------------------------------------------ uptime

def _clock_ticks():
    try:
        return float(os.sysconf("SC_CLK_TCK")) or 100.0
    except (ValueError, OSError, AttributeError):
        return 100.0


def boot_relative_uptime(path="/proc/uptime"):
    """Seconds since boot. One number, no contents of anything."""
    try:
        with open(path) as handle:
            return float(handle.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def process_start(pid, proc="/proc"):
    """Field 22 of `/proc/<pid>/stat`: when the process started, in ticks
    since boot. Doubles as the half of an instance key that a recycled pid
    cannot forge."""
    try:
        with open(os.path.join(proc, str(int(pid)), "stat")) as handle:
            stat = handle.read()
    except (OSError, ValueError):
        return None
    # The comm field is parenthesised and may contain spaces, so everything is
    # counted from the last close parenthesis: field 22 is the 20th after it.
    tail = stat[stat.rfind(")") + 1:].split()
    if len(tail) < 20:
        return None
    try:
        return float(tail[19])
    except ValueError:
        return None


def window_uptime(pid, proc="/proc"):
    """How long the window's process has been alive, in seconds.

    Both halves come out of the same directory - `<proc>/uptime` and
    `<proc>/<pid>/stat` - so a test can hand this a fixture directory and get
    a window of any age it likes.
    """
    started = process_start(pid, proc)
    if started is None:
        return 0.0
    up = boot_relative_uptime(os.path.join(proc, "uptime"))
    return max(0.0, up - started / _clock_ticks())


def instance_key(pid, proc="/proc"):
    """A key for one running window that a recycled pid cannot collide with.

    pid alone is not enough - pids wrap - so the process start time goes in
    too. A pid nobody can read is not tracked at all, and an untracked window
    simply cannot be fed.
    """
    started = process_start(pid, proc)
    if started is None:
        return ""
    return "%d:%d" % (int(pid), int(started))


# ------------------------------------------------------------------- agents
#
# Claude Code, Codex and the rest are not windows. They run inside a terminal
# that goes on calling itself foot, and the title they set is the name of
# whatever you are working on - "Sleeping windows persistence" - not their
# own. So the only honest place left to look is the process tree: the window
# has a pid, the agent is one of its descendants, and `/proc/<pid>/comm` says
# `claude` in as many letters.
#
# That is a reading of something real, the way every other number here is,
# and it costs a handful of small files under /proc. It is also the only
# thing in this module that reads a process it did not start - kept to comm
# and cmdline, both of which `ps` prints for anyone who asks.

AGENT_SCAN_DEPTH = 8        # foot -> shell -> agent, with room for tmux, ssh
AGENT_SCAN_LIMIT = 96       # processes looked at before giving up
AGENT_CACHE_SECONDS = 4.0   # a tree is walked at most this often per window

# Interpreters that are never the agent: when one of these is the command,
# what it is running is (`node .../codex`, `python -m aider`).
AGENT_RUNNERS = ("node", "nodejs", "bun", "deno", "python", "python3", "uv",
                 "uvx", "npx", "pnpm", "ruby", "perl", "sh", "bash", "zsh")

_agent_cache = {}


def _children(pid, proc="/proc"):
    """The pids this one has spawned, out of `/proc/<pid>/task/*/children`."""
    kids = []
    tasks = os.path.join(proc, str(int(pid)), "task")
    try:
        names = os.listdir(tasks)
    except OSError:
        return kids
    for tid in names:
        try:
            with open(os.path.join(tasks, tid, "children")) as handle:
                text = handle.read()
        except OSError:
            continue
        for part in text.split():
            if part.isdigit():
                kids.append(int(part))
    return kids


def _names_of(pid, proc="/proc"):
    """What a process calls itself: its comm, and the command it was given.

    Both, because a tool installed as a script says its own name in comm
    (`claude`) while one launched through an interpreter hides behind it
    (`node .../codex.js`), and either is a fair answer to "what is running
    in that terminal".
    """
    names = []
    try:
        with open(os.path.join(proc, str(int(pid)), "comm")) as handle:
            names.append(handle.read().strip().lower())
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(proc, str(int(pid)), "cmdline")) as handle:
            argv = [part for part in handle.read().split("\0") if part]
    except (OSError, ValueError):
        argv = []
    # Only the command and its first argument, and every step of the path
    # they name: an agent started through an interpreter is somewhere in
    # `/usr/lib/node_modules/codex/cli.js` and nowhere else on the line.
    # Whole steps, never a substring, so the snapshot directory every shell
    # of mine sources - `~/.claude/shell-snapshots/...` - is not an agent.
    for word in argv[:2]:
        for step in word.strip().lower().split("/"):
            if step.endswith(".js") or step.endswith(".py"):
                step = step.rsplit(".", 1)[0]
            if not step or step in AGENT_RUNNERS:
                continue
            names.append(step)
    return names


def agent_of(pid, proc="/proc"):
    """Which agent is running under this window's process, or "".

    Breadth first, because the agent is usually two steps down and a busy
    shell can have a deep tail of its own; bounded in both directions so a
    runaway tree costs a shrug rather than the panel.
    """
    try:
        root = int(pid)
    except (TypeError, ValueError):
        return ""
    # The directory goes in the key as well: a test hands this a /proc of
    # its own with the same pid in it as the last one did.
    key = (proc, instance_key(root, proc) or str(root))
    now = time.monotonic()
    cached = _agent_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]

    found = ""
    seen = 0
    frontier = _children(root, proc)
    for _ in range(AGENT_SCAN_DEPTH):
        if found or not frontier:
            break
        following = []
        for child in frontier:
            seen += 1
            if seen > AGENT_SCAN_LIMIT:
                break
            for name in _names_of(child, proc):
                tool = rules.AGENT_TOOLS.get(name)
                if tool:
                    found = tool
                    break
            if found:
                break
            following.extend(_children(child, proc))
        if seen > AGENT_SCAN_LIMIT:
            break
        frontier = following

    _agent_cache[key] = (now + AGENT_CACHE_SECONDS, found)
    if len(_agent_cache) > MAX_APPETITE_ENTRIES:
        _agent_cache.clear()
    return found


def agent_in_window(window, proc="/proc"):
    """The agent this window is running. Terminals only: a browser showing
    claude.ai is a browser, and a window with no pid is not running
    anything this machine can see."""
    window = window or {}
    if rules.type_of(window.get("initialClass") or window.get("class")) != "SHELL":
        return ""
    pid = window.get("pid")
    if not pid:
        # No pid means a sleeping creature or a fixture: the title is all
        # there is, and the rules read that themselves.
        return ""
    return agent_of(pid, proc)


# ------------------------------------------------------------------- store

class Store:
    """The record book. Loaded once, saved after every change.

    Two shelves inside one file: what each species has earned, which lasts
    forever, and what each live window has eaten, which lasts as long as the
    window does.
    """

    def __init__(self, path=STORE_PATH, proc="/proc"):
        self.path = path
        self.proc = proc
        self.species = {}
        self.appetite = {}
        self.load()

    # ------------------------------------------------------------- file io

    def load(self):
        try:
            with open(self.path) as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        species = data.get("species")
        appetite = data.get("appetite")
        self.species = species if isinstance(species, dict) else {}
        self.appetite = appetite if isinstance(appetite, dict) else {}

    def save(self):
        self._sweep()
        payload = {"version": 1, "species": self.species,
                   "appetite": self.appetite}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w") as handle:
                json.dump(payload, handle)
            os.replace(temporary, self.path)
        except OSError:
            # A record that cannot be written is a record that is forgotten,
            # which is a worse game but never a broken one.
            pass

    def _sweep(self):
        """Forget what has eaten its last meal: an appetite entry whose window
        is gone. The key carries the start time, so a pid that came back as
        something else does not keep the old entry alive.

        Also forget anything of ours that an older version wrote down, so the
        exemption cleans up after itself rather than needing the file edited
        by hand."""
        for key in [key for key in self.species if ours(key)]:
            del self.species[key]
        alive = {}
        for key, value in self.appetite.items():
            pid, _, started = str(key).partition(":")
            if not pid.isdigit():
                continue
            if instance_key(int(pid), self.proc) == key:
                alive[key] = value
        if len(alive) > MAX_APPETITE_ENTRIES:
            ordered = sorted(alive.items(),
                             key=lambda item: item[1].get("at", 0.0),
                             reverse=True)
            alive = dict(ordered[:MAX_APPETITE_ENTRIES])
        self.appetite = alive

    # ------------------------------------------------------------- species

    def record(self, window):
        """What this window's class has earned so far. Never None."""
        key = species_key(window, self.proc)
        entry = self.species.get(key)
        if not isinstance(entry, dict):
            entry = {}
        moves = entry.get("moves")
        try:
            seen = float(entry.get("seen", 0.0) or 0.0)
        except (TypeError, ValueError):
            seen = 0.0
        return {
            "seen": seen,
            "key": key,
            "xp": max(0, int(entry.get("xp", 0) or 0)),
            "wins": max(0, int(entry.get("wins", 0) or 0)),
            "losses": max(0, int(entry.get("losses", 0) or 0)),
            "meals": max(0, int(entry.get("meals", 0) or 0)),
            # What it has been told to carry. The rules decide whether that
            # is still a legal set; a record that names a move it cannot
            # reach costs a preference, never a fighter.
            "moves": [str(one) for one in moves] if isinstance(moves, list) else [],
        }

    # How stale a "last seen" has to be before a roster read writes it down
    # again. Every open window is touched, or a window that never fought and
    # was never fed would leave no trace at all and could never be asleep;
    # this is what stops that being a write every few seconds.
    SEEN_INTERVAL = 300.0

    def touch(self, windows, now=None):
        """Note that these windows are open. Returns True if anything was
        written down."""
        now = time.time() if now is None else now
        changed = False
        for window in windows or []:
            if not isinstance(window, dict):
                continue
            key = species_key(window, self.proc)
            if ours(key):
                continue
            entry = self.species.get(key)
            if not isinstance(entry, dict):
                self.species[key] = {"xp": 0, "wins": 0, "losses": 0,
                                     "meals": 0, "seen": now}
                changed = True
                continue
            try:
                seen = float(entry.get("seen", 0.0) or 0.0)
            except (TypeError, ValueError):
                seen = 0.0
            if now - seen >= self.SEEN_INTERVAL:
                entry["seen"] = now
                changed = True
        if changed:
            self.save()
        return changed

    def teach(self, window, moves, now=None):
        """Write down which four moves a class carries."""
        record = self.record(window)
        record["moves"] = [str(one) for one in (moves or [])]
        record["seen"] = time.time() if now is None else now
        stored = dict(record)
        stored.pop("key", None)
        self.species[record["key"]] = stored
        self.save()
        return record

    def award(self, window, xp=0, win=0, loss=0, meals=0):
        """Add to a record and write it down. Returns the new record."""
        record = self.record(window)
        record["xp"] += max(0, int(xp))
        record["wins"] += max(0, int(win))
        record["losses"] += max(0, int(loss))
        record["meals"] += max(0, int(meals))
        # When this creature was last anything to anybody, so a list of the
        # closed ones can be put in an order that means something.
        record["seen"] = time.time()
        stored = dict(record)
        stored.pop("key", None)
        self.species[record["key"]] = stored
        self.save()
        return record

    # ------------------------------------------------------------ appetite

    def eaten(self, pid):
        """How much nourishment this window has already taken."""
        key = instance_key(pid, self.proc)
        if not key:
            return 0
        entry = self.appetite.get(key) or {}
        try:
            return max(0, int(entry.get("eaten", 0) or 0))
        except (TypeError, ValueError):
            return 0

    def consume(self, pid, nourish, now=None):
        """Write down a meal against one window. Returns the new total, or
        None when the window cannot be identified and so cannot be fed."""
        key = instance_key(pid, self.proc)
        if not key:
            return None
        entry = self.appetite.get(key) or {}
        try:
            total = max(0, int(entry.get("eaten", 0) or 0))
        except (TypeError, ValueError):
            total = 0
        total += max(0, int(nourish))
        self.appetite[key] = {"eaten": total,
                              "at": now if now is not None else time.time()}
        self.save()
        return total


# ------------------------------------------------------------- the roster
#
# What the bar panel shows, and what `battles-ctl roster` prints. It lives
# here rather than in the daemon because `battles-ctl` answers the same
# question with the daemon stopped, and two copies of this would be two
# answers - the same reason the daemon and the CLI share lib/window_moves.py.

import battle_rules as rules                               # noqa: E402


def _seed(window):
    """The same number the rules hang a creature's stats off - its class,
    not its address, so a learnset and the stats it belongs to cannot drift
    apart across a restart."""
    return rules.key_seed(rules.species_key(window))


def teach(window, slot, move, store, proc="/proc"):
    """Swap one of a window's four moves. Returns a dict like `feed` does:
    `ok`, a `message` to show, and the new set when it took."""
    window = window or {}
    record = store.record(window)
    creature = rules.creature(window, record)
    wanted, problem = rules.teachable(creature["type"], _seed(window),
                                      creature["stage"], creature["level"],
                                      record.get("moves"), slot, move,
                                      name=creature["name"])
    if problem:
        return {"ok": False, "message": problem}

    store.teach(window, wanted)
    taught = rules.move_by_id(move)
    return {
        "ok": True,
        "message": "%s learned %s." % (creature["name"],
                                       taught["name"] if taught else "it"),
        "moves": wanted,
    }


def _one_meal_away(needed, room, shelves):
    """True when one portion that is actually on the shelves, and that this
    creature has the appetite for, would take it over the threshold."""
    for shelf in shelves or []:
        if shelf.get("servings", 0) <= 0:
            continue
        nourish = int(shelf.get("nourish", 0))
        if nourish > room:
            continue
        if rules.xp_for_nourish(nourish) >= needed:
            return True
    return False


def _age(window, proc="/proc"):
    """How long this window's process has been up, and nothing at all when
    there is no process to ask about."""
    pid = (window or {}).get("pid")
    return window_uptime(pid, proc) if pid else 0.0


def instances(window, clients, proc="/proc"):
    """Every open window of this creature's class, eldest first.

    A creature is its class, so two Brave windows are two bodies of one
    creature and not two creatures. The eldest speaks for it: it is the one
    that has bought the appetite, and its address is the one the panel and
    `battles-ctl` are handed back.
    """
    key = species_key(window or {}, proc)
    same = [one for one in clients or []
            if isinstance(one, dict) and species_key(one, proc) == key]
    if not same:
        same = [window or {}]
    return sorted(same, key=lambda one: (-_age(one, proc),
                                         str(one.get("address") or "")))


def stomach(windows, store, proc="/proc"):
    """One class's appetite, and what its windows have eaten against it.

    The appetite is the eldest window's, because an appetite is bought with
    uptime and that is the window that bought it; what every instance has
    eaten counts against that one number. One stomach per creature, or a
    second window of something would double what it can be fed - and a meal
    is experience, which belongs to the class and not to the window.
    """
    oldest = 0.0
    eaten = 0
    for one in windows or []:
        pid = (one or {}).get("pid")
        if not pid:
            continue
        oldest = max(oldest, window_uptime(pid, proc))
        eaten += store.eaten(pid)
    return {"uptime": oldest, "appetite": rules.appetite(oldest),
            "eaten": eaten, "hunger": rules.hunger(oldest, eaten)}


def _mouth(windows, store, proc="/proc"):
    """Which window a meal is written down against.

    The one with the most room of its own, so the entry lands where it is
    least likely to be swept away first, and the eldest when none of them has
    any room left. What may be eaten at all is the class's appetite either
    way; this only decides where the note goes.
    """
    best = None
    for one in windows or []:
        pid = (one or {}).get("pid")
        if not pid or not instance_key(pid, proc):
            continue
        uptime = window_uptime(pid, proc)
        rank = (rules.hunger(uptime, store.eaten(pid)), uptime)
        if best is None or rank > best[0]:
            best = (rank, one)
    return best[1] if best else None


def roster(clients, store, larder=None, now=None, proc="/proc"):
    """Every open window as a creature, with what it has earned and how
    hungry it is. Reads; changes nothing.

    One row per class, however many of its windows are open: everything on a
    row but the address belongs to the class, so two Braves listed twice was
    the same creature written out twice - and two stomachs it never had.
    """
    rows = []
    try:
        shelves = list(larder.stock()) if larder is not None else []
    except Exception:
        shelves = []
    groups = {}
    for window in clients or []:
        if not isinstance(window, dict):
            continue
        key = species_key(window, proc)
        if ours(key):
            continue
        groups.setdefault(key, []).append(window)
    for key, windows in groups.items():
        windows = instances(windows[0], windows, proc)
        window = windows[0]              # the eldest speaks for the class
        record = store.record(window)
        creature = rules.creature(window, record)
        room = stomach(windows, store, proc)
        needed = rules.xp_to_next_stage(creature["xp"])
        # One entry per open window, so a panel can say how many there are
        # and name them, without any of them being a creature of its own.
        bodies = [{
            "address": str(one.get("address") or ""),
            "title": str(one.get("title") or ""),
            "uptime": int(_age(one, proc)),
            "eaten": store.eaten(one["pid"]) if one.get("pid") else 0,
            "canFeed": bool(one.get("pid"))
                       and bool(instance_key(one["pid"], proc)),
        } for one in windows]
        rows.append({
            "address": bodies[0]["address"],
            "key": record["key"],
            "name": creature["name"],
            "title": str(window.get("title") or ""),
            "type": creature["type"],
            "level": creature["level"],
            "stage": creature["stage"],
            "xp": creature["xp"],
            "xpInto": creature["xpInto"],
            "xpNeeded": creature["xpNeeded"],
            "wins": record["wins"],
            "losses": record["losses"],
            "meals": record["meals"],
            "maxHp": creature["maxHp"],
            "attack": creature["attack"],
            "defense": creature["defense"],
            "speed": creature["speed"],
            "moves": [{"name": move["name"], "type": move["type"],
                       "power": move["power"],
                       "id": move.get("id") or rules._identify(move,
                                                              creature["type"])}
                      for move in creature["moves"]],
            # Everything it could carry, learned or not, so a panel can show
            # what is coming as well as what is here.
            "learnset": rules.learnset(creature["type"], _seed(window),
                                       creature["level"], creature["stage"]),
            # How many windows it has open, and who they are. The numbers
            # above and below this line are the class's; these are the only
            # things on the row that belong to one window.
            "count": len(bodies),
            "instances": bodies,
            # The eldest window's uptime, because that is the appetite the
            # creature has, and every instance's meals against it.
            "uptime": int(room["uptime"]),
            "appetite": room["appetite"],
            "eaten": room["eaten"],
            "hunger": room["hunger"],
            "canFeed": any(body["canFeed"] for body in bodies),
            "sleeping": False,
            "seen": record["seen"],
            # How far off evolving it is, and whether one meal on the shelves
            # right now would get it there. The bar icon wears a dot when
            # anything answers yes to the second one: that is the only moment
            # this plugin ever has something to ask of somebody.
            "xpToEvolve": needed,
            "canEvolveNow": bool(needed) and _one_meal_away(needed,
                                                            room["hunger"],
                                                            shelves),
        })
    # Hungriest first is the order somebody feeding wants; a stable tiebreak
    # keeps rows from swapping underneath a cursor between refreshes.
    rows.sort(key=lambda row: (-row["hunger"], row["name"], row["address"]))
    return rows


def sleeping(clients, store, now=None):
    """The creatures whose windows are shut.

    A record outlives its window, so closing something does not end it - it
    puts it down. These have no pid, so no uptime, so no appetite: there is
    nothing alive to be hungry. Their moves are another matter, because moves
    belong to the class and not to the process, and so does everything else
    on the list.

    Nothing happens to them while they sleep, on purpose. Every other number
    in this plugin is a reading of something real - uptime, free memory, dead
    processes - and a closed window produces nothing real to read.
    """
    awake = {species_key(window, store.proc) for window in clients or []
             if isinstance(window, dict)}
    rows = []
    for key in sorted(store.species):
        if key in awake or ours(key):
            continue
        window = sleeping_window(key)
        record = store.record(window)
        creature = rules.creature(window, record)
        rows.append({
            "address": "",
            "key": key,
            "name": creature["name"],
            "title": "",
            "type": creature["type"],
            "level": creature["level"],
            "stage": creature["stage"],
            "xp": creature["xp"],
            "xpInto": creature["xpInto"],
            "xpNeeded": creature["xpNeeded"],
            "wins": record["wins"],
            "losses": record["losses"],
            "meals": record["meals"],
            "maxHp": creature["maxHp"],
            "attack": creature["attack"],
            "defense": creature["defense"],
            "speed": creature["speed"],
            "moves": [{"name": move["name"], "type": move["type"],
                       "power": move["power"],
                       "id": move.get("id") or rules._identify(move,
                                                              creature["type"])}
                      for move in creature["moves"]],
            "learnset": rules.learnset(creature["type"], _seed(window),
                                       creature["level"], creature["stage"]),
            # No windows, so no bodies to count: a sleeping creature is one
            # creature the way a waking one is, and neither is a list.
            "count": 0,
            "instances": [],
            "uptime": 0,
            "appetite": 0,
            "eaten": 0,
            "hunger": 0,
            "canFeed": False,
            "sleeping": True,
            "seen": record["seen"],
            "xpToEvolve": rules.xp_to_next_stage(creature["xp"]),
            "canEvolveNow": False,
        })
    # Most recently up first: a pile that only grows needs an order, and
    # "what you were last doing" is the one anybody would look for.
    rows.sort(key=lambda row: (-row["seen"], row["name"]))
    return rows


def find(identifier, clients, store, proc="/proc"):
    """The window a command is about: a live one by address, or a sleeping
    creature by the class it is remembered under."""
    wanted = str(identifier or "")
    for window in clients or []:
        if isinstance(window, dict) and str(window.get("address") or "") == wanted:
            return window
    key = wanted.strip().lower()
    if key and key in store.species:
        return sleeping_window(key)
    return None


def feed(window, shelf_key, store, larder, now=None, proc="/proc",
         clients=None):
    """Feed one portion to one creature, out of the pantry and into the record.

    Two gates, and they are independent on purpose: the machine has to have
    the food spare (the pantry's ledger) and the creature has to have room
    for it (its appetite, bought with uptime). Either one refusing is a plain
    sentence back, never an exception.

    Given the window list, the creature is every open window of its class and
    they share the one appetite; given none, it is the window handed in. The
    meal is written down against one of those windows, because that is what
    an appetite entry is keyed by, and the experience against the class.

    Returns a dict: `ok`, a `message` to show, and - when something was eaten
    - the `serving`, the new `record`, and `evolved` when the experience
    crossed a stage threshold.
    """
    now = time.time() if now is None else now
    window = window or {}
    windows = instances(window, clients, proc)
    mouth = _mouth(windows, store, proc)
    if mouth is None:
        # A creature with no window open has no process to be hungry with.
        # Nothing is wrong; there is just nothing there to feed.
        name = rules.display_name(window)
        return {"ok": False,
                "message": "%s is closed. Open it and it can eat." % name}
    # From here on the eldest open window is the creature: the record, the
    # name and the evolution are its class's, whichever window was pointed at.
    window = windows[0]
    pid = mouth.get("pid")

    shelves = {shelf["key"]: shelf for shelf in (larder.stock() or [])}
    shelf = shelves.get(str(shelf_key))
    if not shelf:
        return {"ok": False, "message": "There is no such food."}

    room = stomach(windows, store, proc)["hunger"]
    nourish = int(shelf.get("nourish", 0))
    if room < nourish:
        return {"ok": False,
                "message": "%s is too full for that. Older windows eat more."
                           % rules.display_name(window)}
    if shelf.get("servings", 0) <= 0:
        return {"ok": False,
                "message": "There is no %s spare." % shelf["name"]}

    serving = larder.take(shelf["key"], None)
    if not serving:
        return {"ok": False,
                "message": "The %s went before you could take it."
                           % shelf["name"]}

    before = rules.creature(window, store.record(window))
    store.consume(pid, nourish, now)
    record = store.award(window, xp=rules.xp_for_nourish(nourish), meals=1)
    after = rules.creature(window, record)

    return {
        "ok": True,
        # The name it had when it ate: the evolution the meal paid for is the
        # next sentence, not this one.
        "message": "%s ate the %s." % (before["name"], shelf["name"]),
        "serving": {"key": shelf["key"], "name": shelf["name"],
                    "nourish": nourish},
        "record": record,
        "level": after["level"],
        "leveled": after["level"] > before["level"],
        "evolved": after["stage"] if after["stage"] > before["stage"] else 0,
        "creature": after,
    }
