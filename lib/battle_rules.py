"""The rules of a window battle: creatures, damage, and the turn loop.

This module is deliberately pure. It knows nothing about evdev, Hyprland,
sockets or QML - it turns two `hyprctl clients` entries into two creatures and
then runs a turn-based fight between them, handing out a snapshot after every
change for something else to draw. That is what makes it testable without a
gamepad, a compositor or a screen (see tests/gamepad.py).

Everything is derived from the windows themselves, so the same two windows
always meet as the same two creatures: the class picks the type, the window's
pixel area picks the level, and the address seeds the stats and the move list.
A battle also seeds its own random number generator from both addresses, which
keeps a rematch recognisable without making it identical.

Nothing here can affect a window. The caller decides what a result means; the
worst this module can ask for is that two windows swap places.
"""

import math
import random

# ------------------------------------------------------------------- types
#
# Seven types, named after what windows actually do rather than after the
# elements of any particular game. They form a ring: each type hits the next
# one hard and bounces off the one before it. A ring is easy to hold in your
# head after two battles, and it cannot produce an unwinnable matchup the way
# a hand-written chart can.

TYPES = ("SHELL", "CODE", "NET", "CHAT", "MEDIA", "GAME", "GLASS")

SUPER_EFFECTIVE = 2.0
NOT_VERY_EFFECTIVE = 0.5
STAB = 1.5              # same-type attack bonus
CRITICAL_CHANCE = 1 / 16.0
CRITICAL_MULTIPLIER = 1.5

# Substrings matched against the window class, most specific first. Anything
# that matches nothing is GLASS, which is the type every desktop window shares
# when it is nothing more interesting than a window.
CLASS_TYPES = (
    ("SHELL", ("foot", "alacritty", "kitty", "ghostty", "wezterm", "urxvt",
               "xterm", "terminal", "konsole", "tilix", "term")),
    ("CODE", ("code", "vscodium", "jetbrains", "idea", "pycharm", "webstorm",
              "clion", "rider", "goland", "rubymine", "android-studio",
              "neovim", "nvim", "vim", "emacs", "zed", "sublime", "cursor",
              "helix", "lapce")),
    ("NET", ("firefox", "chromium", "chrome", "brave", "zen", "librewolf",
             "vivaldi", "epiphany", "qutebrowser", "falkon", "midori",
             "tor-browser", "safari", "edge")),
    ("CHAT", ("discord", "slack", "signal", "telegram", "element", "teams",
              "whatsapp", "thunderbird", "evolution", "geary", "mail",
              "matrix", "zulip", "mumble", "zoom")),
    ("MEDIA", ("mpv", "vlc", "spotify", "obs", "gimp", "inkscape", "blender",
               "audacity", "kdenlive", "krita", "darktable", "ardour",
               "rhythmbox", "clementine", "celluloid", "video", "music",
               "player", "image")),
    ("GAME", ("steam", "lutris", "heroic", "gamescope", "retroarch",
              "minecraft", "wine", "proton", "dolphin-emu", "pcsx",
              "ppsspp", "yuzu", "godot", "unity", "love")),
)


def type_of(window_class):
    """The type a window class fights as."""
    name = str(window_class or "").lower()
    for kind, needles in CLASS_TYPES:
        for needle in needles:
            if needle in name:
                return kind
    return "GLASS"


def effectiveness(attack_type, defend_type):
    """The type ring: each type beats the next and bounces off the previous."""
    try:
        attacker = TYPES.index(attack_type)
        defender = TYPES.index(defend_type)
    except ValueError:
        return 1.0
    count = len(TYPES)
    if (attacker + 1) % count == defender:
        return SUPER_EFFECTIVE
    if (defender + 1) % count == attacker:
        return NOT_VERY_EFFECTIVE
    return 1.0


# ------------------------------------------------------------------- moves
#
# Three moves per type, so the type ring shows up in the menu as well as in
# the damage. Power is the classic scale (a 40 is a filler, an 85 is the big
# one), and the big ones buy their power with accuracy.

MOVES = {
    "SHELL": (
        {"name": "PIPE BURST", "power": 55, "accuracy": 1.00},
        {"name": "SUDO SLAM", "power": 70, "accuracy": 0.90},
        {"name": "FORK BOMB", "power": 85, "accuracy": 0.70},
    ),
    "CODE": (
        {"name": "STACK TRACE", "power": 45, "accuracy": 1.00},
        {"name": "NULL DEREF", "power": 65, "accuracy": 0.90},
        {"name": "REFACTOR", "power": 80, "accuracy": 0.75},
    ),
    "NET": (
        {"name": "COOKIE JAR", "power": 45, "accuracy": 1.00},
        {"name": "PACKET STORM", "power": 65, "accuracy": 0.90},
        {"name": "DNS FLOOD", "power": 80, "accuracy": 0.75},
    ),
    "CHAT": (
        {"name": "PING SPAM", "power": 50, "accuracy": 1.00},
        {"name": "READ RECEIPT", "power": 60, "accuracy": 0.95},
        {"name": "REPLY ALL", "power": 85, "accuracy": 0.70},
    ),
    "MEDIA": (
        {"name": "KEYFRAME", "power": 50, "accuracy": 1.00},
        {"name": "BASS DROP", "power": 70, "accuracy": 0.90},
        {"name": "RENDER PASS", "power": 85, "accuracy": 0.70},
    ),
    "GAME": (
        {"name": "FRAME DROP", "power": 50, "accuracy": 1.00},
        {"name": "RESPAWN", "power": 65, "accuracy": 0.95},
        {"name": "HEADSHOT", "power": 90, "accuracy": 0.65},
    ),
    "GLASS": (
        {"name": "ALT TAB", "power": 45, "accuracy": 1.00},
        {"name": "RESIZE GRIP", "power": 60, "accuracy": 0.95},
        {"name": "WINDOW SHARD", "power": 80, "accuracy": 0.75},
    ),
}


def _seed_of(address):
    """A window address as an integer, for the stats hung off it."""
    text = str(address or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    try:
        return int(text, 16)
    except ValueError:
        return sum((index + 1) * ord(character)
                   for index, character in enumerate(str(address or "?")))


def species_key(window):
    """The name a creature is remembered under: its launch class, folded.

    Also what its stats are hung off. It used to be the window's address, and
    that was wrong in a way that only showed up once records outlived their
    windows: Hyprland hands out a fresh address on every launch, so a creature
    kept its level across a restart and shuffled its attack, its HP and the
    order it learns moves in. A class does not change, so now none of them do.
    """
    window = window or {}
    for field in ("initialClass", "class"):
        value = str(window.get(field) or "").strip().lower()
        if value:
            return value
    return "window"


def key_seed(key):
    """A species key as a number, deterministically - `hash()` is salted per
    process and would re-roll every creature on every restart."""
    seed = 0x811C9DC5
    for character in str(key or "window"):
        seed = ((seed ^ ord(character)) * 0x01000193) & 0xFFFFFFFF
    return seed


def display_name(window):
    """A creature name from the window, uppercase and short enough to fit.

    The initial class is preferred over the live one because a window that
    renames itself (a browser adopting a site's name, say) should still meet
    you as the same creature.
    """
    for key in ("initialClass", "class", "initialTitle", "title"):
        value = str(window.get(key) or "").strip()
        if value:
            # Strip a reverse-DNS prefix: "org.gnome.Nautilus" is Nautilus.
            if "." in value and " " not in value:
                value = value.rsplit(".", 1)[-1] or value
            value = value.upper()
            return value[:12]
    return "WINDOW"


def size_bonus(window):
    """What a window's size is worth, which is not a lot on purpose.

    Screen area used to be the whole level, and it was unfair: a window that
    refuses to be fullscreened, a 4K monitor against a laptop panel and two
    layouts that tile differently all handed out levels nobody earned. Levels
    are fed and fought for now (see `progress`), and size is left as the small
    sturdiness bonus it deserves to be - a big window is roomier, not better.
    """
    size = window.get("size") or [800, 600]
    try:
        width, height = max(1, int(size[0])), max(1, int(size[1]))
    except (TypeError, ValueError, IndexError):
        width, height = 800, 600
    return max(0, min(SIZE_BONUS_CAP, int(math.sqrt(width * height) / 160)))


# ------------------------------------------------------------- progression
#
# A creature is its window class, and a class is remembered (lib/creatures.py)
# so a level survives closing the window. Everything below is the arithmetic
# of that: what experience buys, when it evolves, and how much a window can
# still eat today. All of it pure - the record comes in as a dict.

BASE_LEVEL = 5              # where a window nobody has ever fed starts
MAX_LEVEL = 50
SIZE_BONUS_CAP = 12

XP_FIRST = 40               # the first level up costs this,
XP_STEP = 20                # and each one after it costs this much more.

XP_PER_NOURISH = 2          # feeding: a portion's nourishment, doubled
XP_WIN_BASE = 20            # winning: the loser's level is the prize
XP_WIN_PER_LEVEL = 6
XP_LOSS_BASE = 5            # losing teaches you something, just not much
XP_LOSS_PER_LEVEL = 1

# Evolution is automatic, at a level. Two thresholds, so a creature that is
# fed steadily goes through both in a week rather than a year.
STAGE_LEVELS = (0, 12, 25)

# What an evolved creature is called. The window keeps its own name - it is
# still your terminal - and earns a word in front of it, drawn from what its
# type is good at. Nothing here is borrowed from anybody's monsters.
STAGE_TITLES = {
    "SHELL": ("", "SUPER", "ROOT"),
    "CODE": ("", "SMART", "PRIME"),
    "NET": ("", "FAST", "HYPER"),
    "CHAT": ("", "LOUD", "OMNI"),
    "MEDIA": ("", "RICH", "ULTRA"),
    "GAME": ("", "PRO", "LEGEND"),
    "GLASS": ("", "CLEAR", "CRYSTAL"),
}

NAME_WIDTH = 12             # what the name plate can draw without clipping


def progress(xp):
    """Experience as a place on the ladder.

    Returns (level, into, needed): the level it buys, how far past it the
    experience is, and what the next one costs. The cost grows with every
    level, so the ladder gets slower rather than stopping, and it stops
    entirely at MAX_LEVEL.
    """
    try:
        remaining = max(0, int(xp))
    except (TypeError, ValueError):
        remaining = 0
    level = BASE_LEVEL
    needed = XP_FIRST
    while level < MAX_LEVEL and remaining >= needed:
        remaining -= needed
        level += 1
        needed += XP_STEP
    if level >= MAX_LEVEL:
        return MAX_LEVEL, 0, 0
    return level, remaining, needed


def xp_for_level(level):
    """The experience a creature needs in total to reach a level."""
    target = max(BASE_LEVEL, min(MAX_LEVEL, int(level)))
    total = 0
    needed = XP_FIRST
    for _ in range(BASE_LEVEL, target):
        total += needed
        needed += XP_STEP
    return total


def xp_to_next_stage(xp):
    """How much more experience this creature needs before it evolves.

    Zero once there is nothing left to evolve into, which is what lets a
    caller ask "is this one close?" without knowing the thresholds.
    """
    level = progress(xp)[0]
    for threshold in STAGE_LEVELS[1:]:
        if level < threshold:
            return max(0, xp_for_level(threshold) - max(0, int(xp or 0)))
    return 0


def stage_for_level(level):
    """Which of the three stages a level is in: 1, 2 or 3."""
    stage = 1
    for index, threshold in enumerate(STAGE_LEVELS):
        if level >= threshold:
            stage = index + 1
    return stage


def evolved_name(name, kind, stage):
    """The creature's name at a stage, cut to what the plate can draw."""
    titles = STAGE_TITLES.get(kind) or STAGE_TITLES["GLASS"]
    title = titles[max(0, min(len(titles), stage) - 1)]
    base = str(name or "WINDOW")
    if not title:
        return base[:NAME_WIDTH]
    room = NAME_WIDTH - len(title) - 1
    if room < 3:
        return base[:NAME_WIDTH]
    return ("%s %s" % (title, base[:room]))[:NAME_WIDTH]


def xp_for_nourish(nourish):
    """What one portion of food is worth as experience."""
    return max(0, int(nourish)) * XP_PER_NOURISH


def xp_for_result(result, foe_level):
    """What a finished battle is worth. A fled battle is worth nothing, the
    way walking away from one always has been."""
    level = max(1, int(foe_level or 1))
    if result == "win":
        return XP_WIN_BASE + XP_WIN_PER_LEVEL * level
    if result == "loss":
        return XP_LOSS_BASE + XP_LOSS_PER_LEVEL * level
    return 0


# Hunger
#
# How much a window can eat is bought with how long it has been open, and
# nothing else. A window opened a minute ago is a hatchling with no appetite;
# one that has been up since this morning can take a proper meal. Uptime comes
# off /proc rather than out of a file this plugin wrote, so closing the panel,
# restarting the daemon or editing the ledger cannot fake it - and reopening
# the window resets the appetite honestly, because that really is a new window.
APPETITE_BASE = 20
APPETITE_PER_HOUR = 18
APPETITE_CAP = 200


def appetite(uptime_seconds):
    """How much nourishment a window this old can hold, all told."""
    try:
        hours = max(0.0, float(uptime_seconds)) / 3600.0
    except (TypeError, ValueError):
        hours = 0.0
    return int(min(APPETITE_CAP, APPETITE_BASE + APPETITE_PER_HOUR * hours))


def hunger(uptime_seconds, eaten):
    """How much it can still eat right now: appetite less what it has had."""
    try:
        taken = max(0, int(eaten))
    except (TypeError, ValueError):
        taken = 0
    return max(0, appetite(uptime_seconds) - taken)


def creature(window, record=None):
    """Turn one `hyprctl clients` entry into a fighter.

    `record` is what the window's class has earned so far (lib/creatures.py):
    experience, and the wins and losses behind it. Without one - a test, a
    first sighting, a store that cannot be read - the creature is simply a
    beginner at BASE_LEVEL, which is what every creature was once.
    """
    window = window or {}
    record = record or {}
    # Hung off what the creature *is*, not off the window it happens to be in
    # today: see species_key.
    seed = key_seed(species_key(window))
    kind = type_of(window.get("initialClass") or window.get("class"))
    level, into, needed = progress(record.get("xp", 0))
    stage = stage_for_level(level)
    bonus = size_bonus(window)

    # Level does the work; the seed only decides what this particular class is
    # naturally good at, and the stage is the bump evolution is worth.
    return {
        "address": str(window.get("address") or ""),
        "name": evolved_name(display_name(window), kind, stage),
        "baseName": display_name(window),
        "type": kind,
        "level": level,
        "stage": stage,
        "xp": max(0, int(record.get("xp", 0) or 0)),
        "xpInto": into,
        "xpNeeded": needed,
        "wins": max(0, int(record.get("wins", 0) or 0)),
        "losses": max(0, int(record.get("losses", 0) or 0)),
        # Roomy on purpose: a fight that ends in three hits is over before
        # the HP bar has finished moving, and the bar is half the fun.
        "maxHp": 70 + level * 4 + bonus * 2 + seed % 24,
        "hp": 70 + level * 4 + bonus * 2 + seed % 24,
        "attack": 10 + level + stage * 3 + (seed >> 4) % 12,
        "defense": 9 + level + bonus + (seed >> 8) % 12,
        "speed": 10 + level + (seed >> 12) % 16,
        "moves": carried(kind, seed, stage, level, record.get("moves")),
    }


def moves_for(kind, seed, stage=1):
    """Four moves: mostly the creature's own type, the rest borrowed.

    Its own keeps the same-type bonus reachable every turn; the borrowed ones
    mean a bad type matchup is something you can play around instead of
    something you simply lose.

    Evolving changes what it may reach for. The moves in each type are listed
    weakest first, and a stage-1 creature is not allowed the last of them - a
    beginner does not get to open with the 85. Stage 2 unlocks it; stage 3
    knows all three of its own type and borrows only once, which is what
    finally makes the evolved form fight differently rather than just harder.
    """
    own = list(MOVES.get(kind) or MOVES["GLASS"])
    stage = max(1, min(3, int(stage or 1)))

    if stage >= 3:
        picked = [dict(move, type=kind) for move in own]
        borrowed = 1
    else:
        pool = own if stage >= 2 else own[:-1]
        first = seed % len(pool)
        # Two of its own, and they have to be two different ones. Indices are
        # compared rather than the dicts, which are copies with a type added
        # and so are never found in the pool they came from.
        second = (seed // 3 + 1) % len(pool)
        if second == first:
            second = (first + 1) % len(pool)
        picked = [dict(pool[first], type=kind), dict(pool[second], type=kind)]
        borrowed = 2

    others = [other for other in TYPES if other != kind]
    for step in range(borrowed):
        borrowed_type = others[(seed >> (5 * (step + 1))) % len(others)]
        pool = MOVES[borrowed_type]
        picked.append(dict(pool[(seed >> (3 * (step + 1))) % len(pool)],
                           type=borrowed_type))
    return picked


# ----------------------------------------------------------- the learnset
#
# Four moves are carried; more than four are known. A creature learns its own
# type's moves by evolving (see `moves_for`) and borrows the rest one at a
# time as it levels, which is what a level between two evolutions is for -
# before this, a level was three numbers going up and nothing to decide.
#
# The order is the creature's own: it comes off the same address seed the
# stats do, so your terminal always learns the same things in the same order
# and no two classes have the same list. None of this is stored here - the
# chosen four live in the record (lib/creatures.py) and are handed back in.

MOVE_UNLOCK_LEVELS = (8, 13, 18, 24, 30)
CARRIED_MOVES = 4
MIN_OWN_MOVES = 2           # the type ring only means something if it is met


def move_id(kind, index):
    """A move's name in a record: its type and its place in that type's
    list, which is stable in a way a printed name is not."""
    return "%s:%d" % (kind, int(index))


def move_by_id(identifier):
    """The move one of those names refers to, or None."""
    kind, _, index = str(identifier or "").partition(":")
    pool = MOVES.get(kind.upper())
    if not pool:
        return None
    try:
        position = int(index)
    except ValueError:
        return None
    if not 0 <= position < len(pool):
        return None
    return dict(pool[position], type=kind.upper(), id=move_id(kind.upper(),
                                                              position))


def _borrowed_order(kind, seed):
    """Every move this creature could ever borrow, in the order it learns
    them. The two it starts with come first, so the moves it was born with
    are always ones it knows."""
    starters = [move for move in moves_for(kind, seed) if move["type"] != kind]
    order, seen = [], set()
    for move in starters:
        identifier = move_id(move["type"], MOVES[move["type"]].index(
            next(other for other in MOVES[move["type"]]
                 if other["name"] == move["name"])))
        if identifier not in seen:
            seen.add(identifier)
            order.append(identifier)

    rest = [move_id(other, index)
            for other in TYPES if other != kind
            for index in range(len(MOVES[other]))]
    rest = [identifier for identifier in rest if identifier not in seen]
    random.Random(seed ^ 0x5EED).shuffle(rest)
    return order + rest


def learnset(kind, seed, level, stage):
    """Everything this creature knows, and what it has yet to learn.

    Locked moves are listed too, with the level they arrive at: a list that
    only shows what you have is a list that never tells you to keep going.
    """
    kind = kind if kind in MOVES else "GLASS"
    stage = max(1, min(3, int(stage or 1)))
    level = max(0, int(level or 0))

    known = []
    own = MOVES[kind]
    # Its own type arrives with evolution, exactly as `moves_for` gates it.
    reachable = len(own) if stage >= 2 else len(own) - 1
    for index in range(len(own)):
        known.append({
            "id": move_id(kind, index),
            "name": own[index]["name"],
            "type": kind,
            "power": own[index]["power"],
            "accuracy": own[index]["accuracy"],
            "known": index < reachable,
            "at": 0 if index < reachable else STAGE_LEVELS[1],
        })

    borrowed = _borrowed_order(kind, seed)
    for position, identifier in enumerate(borrowed[:2 + len(MOVE_UNLOCK_LEVELS)]):
        move = move_by_id(identifier)
        if not move:
            continue
        needed = 0 if position < 2 else MOVE_UNLOCK_LEVELS[position - 2]
        known.append({
            "id": identifier,
            "name": move["name"],
            "type": move["type"],
            "power": move["power"],
            "accuracy": move["accuracy"],
            "known": level >= needed,
            "at": needed,
        })
    return known


def carried(kind, seed, stage, level, chosen=None):
    """The four moves a creature actually fights with.

    `chosen` is what the record says. It is used only if it is a real choice:
    four moves, all of them learned, at least two of them the creature's own.
    Anything else - an empty record, a move it has forgotten how to reach
    after nothing, a hand-edited file - falls back to the four it would have
    had anyway, so a broken record costs a preference and never a fighter.
    """
    default = moves_for(kind, seed, stage)
    if not chosen:
        return default

    allowed = {entry["id"] for entry in learnset(kind, seed, level, stage)
               if entry["known"]}
    picked, seen = [], set()
    for identifier in chosen:
        identifier = str(identifier)
        if identifier in seen or identifier not in allowed:
            return default
        move = move_by_id(identifier)
        if not move:
            return default
        seen.add(identifier)
        picked.append(move)

    if len(picked) != CARRIED_MOVES:
        return default
    if sum(1 for move in picked if move["type"] == kind) < MIN_OWN_MOVES:
        return default
    return picked


def teachable(kind, seed, stage, level, chosen, slot, identifier, name=None):
    """Swap one carried move for another. Returns (moves, message).

    The message is empty when it worked and a plain sentence when it did not;
    nothing here raises, because every refusal is something to show somebody.
    """
    name = name or kind
    current = [move["id"] if "id" in move else _identify(move, kind)
               for move in carried(kind, seed, stage, level, chosen)]
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        return current, "There is no such slot."
    if not 0 <= slot < CARRIED_MOVES:
        return current, "There is no such slot."

    move = move_by_id(identifier)
    if not move:
        return current, "There is no such move."
    entry = next((one for one in learnset(kind, seed, level, stage)
                  if one["id"] == move["id"]), None)
    if not entry:
        return current, "%s cannot learn that." % name
    if not entry["known"]:
        return current, ("%s learns %s at level %d."
                         % (name, move["name"], entry["at"])
                         if entry["at"] else "%s has not learned that yet." % name)
    if move["id"] in current and current[slot] != move["id"]:
        return current, "It already knows that one."

    wanted = list(current)
    wanted[slot] = move["id"]
    if sum(1 for one in wanted
           if str(one).split(":")[0] == kind) < MIN_OWN_MOVES:
        return current, ("It has to keep %d moves of its own type."
                         % MIN_OWN_MOVES)
    return wanted, ""


def _identify(move, kind):
    """The id of a move dict that came out of `moves_for`, which does not
    carry one."""
    pool = MOVES.get(move.get("type") or kind) or ()
    for index, other in enumerate(pool):
        if other["name"] == move.get("name"):
            return move_id(move.get("type") or kind, index)
    return move_id(kind, 0)


def damage(attacker, defender, move, rng):
    """One hit. Returns (amount, effectiveness, critical).

    The shape is the familiar one - level and power up top, the defender's
    defense underneath, a small random spread so the same matchup is never
    quite the same fight - with a floor of 1 so no attack is ever pointless.
    """
    multiplier = effectiveness(move["type"], defender["type"])
    base = ((2.0 * attacker["level"] / 5.0 + 2.0) * move["power"]
            * attacker["attack"] / max(1, defender["defense"])) / 50.0 + 2.0

    critical = rng.random() < CRITICAL_CHANCE
    total = base * multiplier
    if move["type"] == attacker["type"]:
        total *= STAB
    if critical:
        total *= CRITICAL_MULTIPLIER
    total *= rng.uniform(0.85, 1.0)
    return max(1, int(total)), multiplier, critical


def hits(move, rng):
    return rng.random() < move.get("accuracy", 1.0)


def effect_note(multiplier):
    if multiplier > 1.0:
        return "It's super effective!"
    if multiplier < 1.0:
        return "It's not very effective..."
    return ""


# ------------------------------------------------------------------ trigger

BATTLE_CHANCE = 0.25


def should_battle(rng, chance=BATTLE_CHANCE):
    """The roll a colliding gamepad move makes. Split out so the odds are
    one number, in one place, that a test can hold still."""
    return rng.random() < chance


def battle_seed(first_address, second_address):
    """Both addresses, so a rematch between the same two windows plays out
    the same way while a different pairing does not."""
    return (_seed_of(first_address) * 1000003) ^ _seed_of(second_address)


# ------------------------------------------------------------- the turn loop

# The top-level choice, in front of the move list, the way the games this is
# imitating do it: you decide whether to fight at all before you decide how.
ACTIONS = ("FIGHT", "ITEM", "RUN")

# Eating
#
# Food is a real reading off the machine (lib/pantry.py) rather than a stash,
# so a battle is handed a larder to ask rather than a list to hold. A meal
# heals a fraction of the creature's own maximum HP, so a big window and a
# small one both get something that means something, and it costs the turn:
# the other window gets a free swing while you are chewing.
#
# Nourishment accumulates across the battle, and a creature that has eaten
# enough of it goes up a level. That is the one way a creature gets stronger
# mid-fight, and it is what the level-up sting has been waiting for.
NOURISH_PER_LEVEL = 60
LEVEL_UP_HP = 8             # maximum HP gained with a level
LEVEL_UP_STAT = 2           # and each of attack, defense and speed


class NoLarder:
    """The pantry when there is nothing to ask - tests, or a machine whose
    /proc is not where it should be. Every shelf is bare, and ITEM says so."""

    @staticmethod
    def stock(now=None):
        return []

    @staticmethod
    def take(key, now=None):
        return None

# Running away always works before the first blow is struck - walking into
# something and immediately deciding against it should never be punished. Once
# you have actually swung at it, getting out is a gamble: faster creatures get
# away more often, and every failed attempt improves the next one, so RUN is a
# real decision rather than a free exit.
#
# None of this is the escape hatch. START, SELECT and Escape end a battle
# outright, whatever the odds here say; this is the in-fiction version.
RUN_BASE = 0.30
RUN_SPEED_WEIGHT = 0.35
RUN_ATTEMPT_BONUS = 0.15
RUN_FLOOR = 0.20
RUN_CEILING = 0.95


def run_chance(player, foe, attempts):
    """The odds of getting away, once the fight has actually started."""
    ratio = min(2.0, player["speed"] / float(max(1, foe["speed"])))
    chance = (RUN_BASE + RUN_SPEED_WEIGHT * ratio / 2.0
              + RUN_ATTEMPT_BONUS * attempts)
    return max(RUN_FLOOR, min(RUN_CEILING, chance))

TEXT_DWELL = 1.7        # seconds a line of text stays up before it advances
HIT_DWELL = 0.8         # and the shorter beat a hit animation gets
MENU_TIMEOUT = 25.0     # nobody has touched the pad: end it rather than wait
HARD_TIMEOUT = 180.0    # an upper bound on a battle, whatever else happens
RESULT_DWELL = 3.2      # how long the closing line stays up


class Battle:
    """The state machine. Every public method returns True when something
    changed, so the caller knows when to publish a new snapshot."""

    def __init__(self, player, foe, now, rng=None, direction="", monitor="",
                 larder=None):
        self.player = player
        self.foe = foe
        self.direction = direction
        self.monitor = monitor
        # Where food comes from. Asked, never held: see lib/pantry.py.
        self.larder = larder if larder is not None else NoLarder()
        self.rng = rng or random.Random(
            battle_seed(player.get("address"), foe.get("address")))

        # intro | action | menu | item | resolve | over. `action` is the
        # FIGHT/ITEM/RUN menu the fight opens on; `menu` is the move list
        # behind FIGHT, and `item` the pantry behind ITEM.
        self.phase = "intro"
        self.result = ""            # win | loss | draw, once phase is over
        self.cursor = 0
        self.queue = []
        self.message = ""
        self.effect = ""            # hit-foe | hit-player | faint-foe | ...
        self.turn = 0
        self.run_attempts = 0
        # What is on the shelves, read when ITEM is opened, and how much the
        # challenger has eaten so far this battle.
        self.shelves = []
        self.fed = 0
        self.seq = 0
        self.started_at = now
        self.next_at = now + TEXT_DWELL
        self.ends_at = now + HARD_TIMEOUT
        self.closed_at = None

        self._say("A wild %s blocked the way!" % self.foe["name"])
        self._say("%s was thrown at it!" % self.player["name"])
        self._pop(now)

    # ------------------------------------------------------------ helpers

    def _say(self, text, effect="", apply=None, dwell=TEXT_DWELL):
        self.queue.append({"text": text, "effect": effect, "apply": apply,
                           "dwell": dwell})

    def _pop(self, now):
        """Show the next queued line, applying whatever it does.

        A step with no text is an animation beat - the hit flash, the HP bar
        draining - so the line already on screen stays put underneath it
        rather than blanking for a moment.
        """
        if not self.queue:
            return False
        step = self.queue.pop(0)
        if step["text"]:
            self.message = step["text"]
        self.effect = step["effect"]
        if step["apply"]:
            step["apply"]()
        self.next_at = now + step["dwell"]
        self.seq += 1
        return True

    def _hurt(self, target, amount):
        def apply():
            target["hp"] = max(0, target["hp"] - amount)
        return apply

    @property
    def active(self):
        return self.phase != "over" or self.closed_at is not None

    @property
    def menu_open(self):
        return self.phase == "menu"

    @property
    def choosing(self):
        """A menu is up, so the battle is waiting on the player."""
        return self.phase in ("action", "menu", "item")

    def moves(self):
        return self.player["moves"]

    # -------------------------------------------------------------- input

    def move_cursor(self, direction):
        """The menus, driven by the d-pad.

        FIGHT/RUN is a short list walked with up and down; the move list is a
        2x2 grid where left and right pick the column.
        """
        if self.phase == "action":
            return self._grid_cursor(direction, len(ACTIONS))
        if self.phase == "item":
            return self._grid_cursor(direction, len(self.shelves))
        if self.phase != "menu":
            return False
        return self._grid_cursor(direction, len(self.moves()))

    def _grid_cursor(self, direction, count, columns=2):
        """A two-column grid, walked one cell at a time in all four directions.

        The action menu, the move list and the pantry are all laid out this
        way, so the same hand movement means the same thing everywhere. A grid
        that does not divide evenly has a hole in the last row, and the cursor
        refuses to move into it rather than wrapping somewhere surprising.
        """
        column, row = self.cursor % columns, self.cursor // columns
        if direction == "l":
            column -= 1
        elif direction == "r":
            column += 1
        elif direction == "u":
            row -= 1
        elif direction == "d":
            row += 1
        else:
            return False
        if column < 0 or column >= columns or row < 0:
            return False
        cursor = row * columns + column
        if cursor == self.cursor or not 0 <= cursor < count:
            return False
        self.cursor = cursor
        self.seq += 1
        return True

    def confirm(self, now):
        """A on the pad: take the highlighted option, or advance the text."""
        if self.phase == "action":
            chosen = ACTIONS[self.cursor]
            if chosen == "RUN":
                return self.try_run(now)
            if chosen == "ITEM":
                return self.open_pantry(now)
            # FIGHT: open the move list.
            self.phase = "menu"
            self.cursor = 0
            self.next_at = now + MENU_TIMEOUT
            self.seq += 1
            return True
        if self.phase == "menu":
            return self.play(self.cursor, now)
        if self.phase == "item":
            return self.eat(self.cursor, now)
        return self.advance(now)

    def try_run(self, now):
        """RUN from the action menu: certain before the first exchange, a roll
        after it, and a failed roll hands the other window a free hit."""
        if self.phase != "action":
            return False
        if self.turn == 0:
            return self.flee(now, "draw")

        self.run_attempts += 1
        if self.rng.random() < run_chance(self.player, self.foe,
                                          self.run_attempts - 1):
            return self.flee(now, "draw")

        self.phase = "resolve"
        self._say("%s could not get away!" % self.player["name"])
        if self.foe["hp"] > 0 and self.player["hp"] > 0:
            self._resolve(self.foe, self.player, moves_choice(self.foe, self.rng),
                          "player", self.player["hp"])
        self._pop(now)
        return True

    def back(self, now):
        """B on the pad: out of a submenu, back to FIGHT/ITEM/RUN."""
        if self.phase not in ("menu", "item"):
            return False
        self.phase = "action"
        self.cursor = 0
        self.next_at = now + MENU_TIMEOUT
        self.seq += 1
        return True

    # --------------------------------------------------------------- eating

    def open_pantry(self, now):
        """ITEM: take a live reading of the machine and show what is spare."""
        if self.phase != "action":
            return False
        try:
            self.shelves = list(self.larder.stock(now))
        except Exception:
            # A pantry that cannot be read is an empty one, never a crash.
            self.shelves = []
        self.phase = "item"
        self.cursor = 0
        self.next_at = now + MENU_TIMEOUT
        self.seq += 1
        return True

    def eat(self, index, now):
        """Feed the highlighted shelf to the challenger, and lose the turn."""
        if self.phase != "item":
            return False
        if not 0 <= index < len(self.shelves):
            return False
        shelf = self.shelves[index]

        if shelf.get("servings", 0) <= 0:
            # Nothing there. Say so and stay in the menu rather than burning
            # a turn on an empty shelf.
            self.message = "There is no %s spare." % shelf["name"]
            self.effect = ""
            self.seq += 1
            return True

        # The larder writes the ledger; it can still refuse if the reading
        # moved between opening the menu and choosing.
        serving = None
        try:
            serving = self.larder.take(shelf["key"], now)
        except Exception:
            serving = None
        if not serving:
            self.message = "The %s went before you could take it." % shelf["name"]
            self.effect = ""
            self.seq += 1
            return True

        self.phase = "resolve"
        self.turn += 1
        self._serve(serving)

        # Eating costs the turn: the other window gets a free swing.
        if self.player["hp"] > 0 and self.foe["hp"] > 0:
            self._resolve(self.foe, self.player, moves_choice(self.foe, self.rng),
                          "player", self.player["hp"])
        self._pop(now)
        return True

    def _serve(self, shelf):
        """Queue what one portion does. Heals, then whatever else it is."""
        name = shelf["name"]
        self._say("%s ate the %s!" % (self.player["name"], name))

        healed = self._heal_for(shelf)
        if healed > 0:
            self._say("", "heal-player", self._restore(self.player, healed),
                      HIT_DWELL)
            self._say("%s recovered %d HP!" % (self.player["name"], healed))
        else:
            self._say("...nothing happened.")

        penalty = shelf.get("penalty")
        if penalty:
            self._say("%s is weighed down." % self.player["name"],
                      apply=self._adjust(penalty, -1))
        boon = shelf.get("boon")
        if boon:
            self._say("%s feels fiercer!" % self.player["name"],
                      apply=self._adjust(boon, 1))

        self.fed += int(shelf.get("nourish", 0))
        while self.fed >= NOURISH_PER_LEVEL:
            self.fed -= NOURISH_PER_LEVEL
            self._say("%s grew to level %d!" % (self.player["name"],
                                                self.player["level"] + 1),
                      "level-up", self._level_up())

    def _heal_for(self, shelf):
        """How much one portion restores.

        Everything but candy is what it says on the shelf. Candy is entropy,
        so it does what entropy does: sometimes a lot, sometimes nothing, and
        occasionally it disagrees with you.
        """
        fraction = float(shelf.get("heal", 0.0))
        if shelf.get("kind") == "candy":
            fraction *= self.rng.choice((0.0, 0.5, 1.0, 1.5, 2.0))
        missing = self.player["maxHp"] - self.player["hp"]
        return min(missing, int(self.player["maxHp"] * fraction))

    def _restore(self, target, amount):
        def apply():
            target["hp"] = min(target["maxHp"], target["hp"] + amount)
        return apply

    def _adjust(self, change, sign):
        """A lasting stat change for the rest of the battle. Floors at 1, so
        nothing can be eaten into uselessness."""
        stat = change["stat"]
        fraction = float(change["fraction"]) * sign

        def apply():
            current = self.player[stat]
            self.player[stat] = max(1, int(round(current * (1.0 + fraction))))
        return apply

    def _level_up(self):
        def apply():
            self.player["level"] += 1
            self.player["maxHp"] += LEVEL_UP_HP
            self.player["hp"] += LEVEL_UP_HP
            for stat in ("attack", "defense", "speed"):
                self.player[stat] += LEVEL_UP_STAT
        return apply

    def advance(self, now):
        """Show the next line early, or leave the text phase when it is done."""
        if self.phase == "over":
            return False
        if self.queue:
            return self._pop(now)
        return self._settle(now)

    def play(self, index, now):
        """Resolve one exchange: both creatures act, faster one first."""
        if self.phase != "menu":
            return False
        moves = self.moves()
        if not 0 <= index < len(moves):
            return False

        self.phase = "resolve"
        self.turn += 1
        self.cursor = index

        foe_move = moves_choice(self.foe, self.rng)
        order = [(self.player, self.foe, moves[index], "foe"),
                 (self.foe, self.player, foe_move, "player")]
        # Speed decides who swings first; the window being thrown gets the tie,
        # which is the only advantage it has for starting the fight.
        if self.foe["speed"] > self.player["speed"]:
            order.reverse()

        # The whole exchange is queued up front, but the HP only actually
        # moves when each line reaches the screen. Track where the HP will be
        # by the time a step runs, so the second attacker does not get a turn
        # it has already been knocked out of.
        pending = {"player": self.player["hp"], "foe": self.foe["hp"]}
        for attacker, defender, move, side in order:
            # `side` names who is being hit, so the attacker is the other one.
            attacker_side = "player" if side == "foe" else "foe"
            if pending[attacker_side] <= 0 or pending[side] <= 0:
                continue
            pending[side] -= self._resolve(attacker, defender, move, side,
                                           pending[side])

        self._pop(now)
        return True

    def _resolve(self, attacker, defender, move, side, defender_hp):
        """Queue one attack. Returns the damage it will have done."""
        self._say("%s used %s!" % (attacker["name"], move["name"]))
        if not hits(move, self.rng):
            self._say("%s missed!" % attacker["name"])
            return 0

        amount, multiplier, critical = damage(attacker, defender, move, self.rng)
        self._say("", "hit-" + side, self._hurt(defender, amount), HIT_DWELL)
        if critical:
            self._say("A critical hit!")
        note = effect_note(multiplier)
        if note:
            self._say(note)
        if defender_hp - amount <= 0:
            self._say("%s fainted!" % defender["name"], "faint-" + side)
        return amount

    def flee(self, now, reason="draw"):
        """The escape hatch. A fled battle changes nothing: the move that
        started it simply stands, exactly as it would have without a battle."""
        if self.phase == "over":
            return False
        self.queue = []
        self.phase = "over"
        self.result = reason
        self.message = ("Got away safely!" if reason == "draw"
                        else "The battle was called off.")
        self.effect = ""
        self.closed_at = now + RESULT_DWELL
        self.seq += 1
        return True

    # ------------------------------------------------------------- ticking

    def _settle(self, now):
        """The queue is empty: either somebody fainted, or it is your turn."""
        if self.foe["hp"] <= 0 or self.player["hp"] <= 0:
            self.phase = "over"
            self.result = "win" if self.foe["hp"] <= 0 else "loss"
            self.message = ("%s won the cell!" % self.player["name"]
                            if self.result == "win"
                            else "%s held its ground." % self.foe["name"])
            self.effect = "result-" + self.result
            self.closed_at = now + RESULT_DWELL
            self.seq += 1
            return True

        self.phase = "action"
        self.cursor = 0
        self.message = "What will %s do?" % self.player["name"]
        self.effect = ""
        self.next_at = now + MENU_TIMEOUT
        self.seq += 1
        return True

    def tick(self, now):
        """Time passing: text advances itself, and nothing runs forever."""
        if self.phase == "over":
            return False
        if now >= self.ends_at:
            return self.flee(now, "draw")
        if now < self.next_at:
            return False
        if self.choosing:
            # Nobody is playing. Walk away rather than hold the screen.
            return self.flee(now, "draw")
        return self.advance(now)

    def finished(self, now):
        """True once the closing line has had its time on screen."""
        return self.phase == "over" and (self.closed_at is None
                                         or now >= self.closed_at)

    def deadline(self):
        """When tick() next has something to do, for the daemon's select()."""
        if self.phase == "over":
            return self.closed_at
        return min(self.next_at, self.ends_at)

    # ------------------------------------------------------------ snapshot

    def snapshot(self):
        """Everything the overlay draws, and nothing it does not."""
        return {
            "active": True,
            "scene": "battle",
            "phase": self.phase,
            "result": self.result,
            "message": self.message,
            "effect": self.effect,
            "seq": self.seq,
            "turn": self.turn,
            "cursor": self.cursor,
            "monitor": self.monitor,
            "direction": self.direction,
            "menu": self.phase == "menu",
            "action": self.phase == "action",
            "item": self.phase == "item",
            "actions": list(ACTIONS),
            "runAttempts": self.run_attempts,
            "fed": self.fed,
            "nourishPerLevel": NOURISH_PER_LEVEL,
            "shelves": [
                {"key": shelf["key"], "name": shelf["name"],
                 "note": shelf["note"], "unit": shelf["unit"],
                 "kind": shelf["kind"], "portion": shelf["portion"],
                 "available": shelf["available"], "servings": shelf["servings"]}
                for shelf in self.shelves
            ],
            "moves": [
                {"name": move["name"], "type": move["type"],
                 "power": move["power"]}
                for move in self.moves()
            ],
            "player": _side(self.player),
            "foe": _side(self.foe),
        }


def _side(fighter):
    return {
        "address": fighter["address"],
        "name": fighter["name"],
        "type": fighter["type"],
        "level": fighter["level"],
        "stage": fighter.get("stage", 1),
        "hp": fighter["hp"],
        "maxHp": fighter["maxHp"],
    }


# ---------------------------------------------------------------- evolving
#
# The other thing the overlay can be asked to draw. It is not a battle - no
# turns, no menus, nothing to play - so it is not a Battle with the fighting
# taken out; it is its own small state machine with the same shape (tick,
# advance, finished, snapshot) so the daemon drives both the same way.
#
# It runs on screen because a level that goes up in a file nobody opens is
# not a reward. The window itself is the picture, exactly as in a battle.

EVOLVE_INTRO = 2.0          # "...is evolving!"
EVOLVE_SHIFT = 2.6          # the long bright beat where it changes
EVOLVE_DONE = 3.0           # "...evolved into ...!"


class Evolution:
    """One creature crossing a stage threshold, as three beats on screen."""

    def __init__(self, creature_before, stage, now, monitor=""):
        self.creature = creature_before
        self.stage = max(2, min(3, int(stage)))
        self.monitor = monitor
        # The creature handed in is already the evolved one - the record was
        # written before the picture was drawn, so an escape mid-animation
        # cannot lose the level. Both names are rebuilt from its base name,
        # which is the window's own and does not change with the stage.
        base = creature_before.get("baseName") or creature_before.get("name")
        kind = creature_before.get("type")
        self.before = evolved_name(base, kind, self.stage - 1)
        self.after = evolved_name(base, kind, self.stage)
        self.phase = "intro"
        self.effect = "evolve-intro"
        self.message = "What? %s is evolving!" % self.before
        self.seq = 1
        self.next_at = now + EVOLVE_INTRO
        self.ends_at = now + EVOLVE_INTRO + EVOLVE_SHIFT + EVOLVE_DONE + 1.0
        self.closed_at = None

    @property
    def active(self):
        return self.phase != "over" or self.closed_at is not None

    def advance(self, now):
        """Move to the next beat. Returns True when anything changed."""
        if self.phase == "intro":
            self.phase = "shift"
            self.effect = "evolve-shift"
            # The line stays up through the flash. An empty text box under a
            # creature that is changing shape reads as something breaking.
            self.next_at = now + EVOLVE_SHIFT
        elif self.phase == "shift":
            self.phase = "done"
            self.effect = "evolve-done"
            self.message = "%s evolved into %s!" % (self.before, self.after)
            self.next_at = now + EVOLVE_DONE
        elif self.phase == "done":
            self.phase = "over"
            self.effect = ""
            self.closed_at = now
        else:
            return False
        self.seq += 1
        return True

    def tick(self, now):
        if self.phase == "over":
            return False
        if now >= self.ends_at or now >= self.next_at:
            return self.advance(now)
        return False

    def flee(self, now, reason="draw"):
        """Escape. The evolution itself has already been written down, so
        skipping the picture costs nothing but the picture."""
        if self.phase == "over":
            return False
        self.phase = "over"
        self.effect = ""
        self.closed_at = now
        self.seq += 1
        return True

    def finished(self, now):
        return self.phase == "over"

    def deadline(self):
        return self.closed_at if self.phase == "over" else self.next_at

    def snapshot(self):
        creature = dict(self.creature)
        evolved = self.phase in ("done", "over")
        creature["name"] = self.after if evolved else self.before
        creature["stage"] = self.stage if evolved else max(1, self.stage - 1)
        return {
            "active": True,
            "scene": "evolve",
            "phase": self.phase,
            "message": self.message,
            "effect": self.effect,
            "seq": self.seq,
            "monitor": self.monitor,
            "before": self.before,
            "after": self.after,
            "stage": self.stage,
            "player": _side(creature),
        }


def moves_choice(fighter, rng):
    """What the other window does on its turn.

    It leans towards the move that would hurt most against the type in front
    of it, but not every time, so a defender is neither a pushover nor a
    machine.
    """
    moves = fighter["moves"]
    if rng.random() < 0.3:
        return rng.choice(moves)
    return max(moves, key=lambda move: move["power"] * move.get("accuracy", 1.0))
