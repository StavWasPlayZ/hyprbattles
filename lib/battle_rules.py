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

TYPES = ("SHELL", "CODE", "NET", "CHAT", "MEDIA", "PIXEL", "GLASS")

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
    ("PIXEL", ("steam", "lutris", "heroic", "gamescope", "retroarch",
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
    "PIXEL": (
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


def level_of(window):
    """Bigger windows are higher level. Screen real estate is the only
    currency a window has, so it is the one the level is bought with."""
    size = window.get("size") or [800, 600]
    try:
        width, height = max(1, int(size[0])), max(1, int(size[1]))
    except (TypeError, ValueError, IndexError):
        width, height = 800, 600
    return max(3, min(40, 3 + int(math.sqrt(width * height) / 100)))


def creature(window):
    """Turn one `hyprctl clients` entry into a fighter."""
    window = window or {}
    seed = _seed_of(window.get("address"))
    kind = type_of(window.get("initialClass") or window.get("class"))
    level = level_of(window)

    return {
        "address": str(window.get("address") or ""),
        "name": display_name(window),
        "type": kind,
        "level": level,
        # Roomy on purpose: a fight that ends in three hits is over before
        # the HP bar has finished moving, and the bar is half the fun.
        "maxHp": 80 + level * 3 + seed % 24,
        "hp": 80 + level * 3 + seed % 24,
        "attack": 12 + level + (seed >> 4) % 14,
        "defense": 10 + level + (seed >> 8) % 14,
        "speed": 10 + level + (seed >> 12) % 18,
        "moves": moves_for(kind, seed),
    }


def moves_for(kind, seed):
    """Four moves: two of the creature's own type, two borrowed.

    Two of its own keeps the same-type bonus reachable every turn; two
    borrowed means a bad type matchup is something you can play around
    instead of something you simply lose.
    """
    own = list(MOVES.get(kind) or MOVES["GLASS"])
    first = seed % len(own)
    second = (seed // 3 + 1) % len(own)
    # Two of its own, and they have to be two different ones. Indices are
    # compared rather than the dicts, which are copies with a type added and
    # so are never found in the pool they came from.
    if second == first:
        second = (first + 1) % len(own)
    picked = [dict(own[first], type=kind), dict(own[second], type=kind)]

    others = [other for other in TYPES if other != kind]
    for step in range(2):
        borrowed_type = others[(seed >> (5 * (step + 1))) % len(others)]
        pool = MOVES[borrowed_type]
        picked.append(dict(pool[(seed >> (3 * (step + 1))) % len(pool)],
                           type=borrowed_type))
    return picked


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
ACTIONS = ("FIGHT", "RUN")

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

    def __init__(self, player, foe, now, rng=None, direction="", monitor=""):
        self.player = player
        self.foe = foe
        self.direction = direction
        self.monitor = monitor
        self.rng = rng or random.Random(
            battle_seed(player.get("address"), foe.get("address")))

        # intro | action | menu | resolve | over. `action` is the FIGHT/RUN
        # menu the fight opens on; `menu` is the move list behind FIGHT.
        self.phase = "intro"
        self.result = ""            # win | loss | draw, once phase is over
        self.cursor = 0
        self.queue = []
        self.message = ""
        self.effect = ""            # hit-foe | hit-player | faint-foe | ...
        self.turn = 0
        self.run_attempts = 0
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
        """Either menu is up, so the battle is waiting on the player."""
        return self.phase in ("action", "menu")

    def moves(self):
        return self.player["moves"]

    # -------------------------------------------------------------- input

    def move_cursor(self, direction):
        """The menus, driven by the d-pad.

        FIGHT/RUN is a short list walked with up and down; the move list is a
        2x2 grid where left and right pick the column.
        """
        if self.phase == "action":
            if direction == "u":
                cursor = 0
            elif direction == "d":
                cursor = len(ACTIONS) - 1
            else:
                return False
            if cursor == self.cursor:
                return False
            self.cursor = cursor
            self.seq += 1
            return True
        if self.phase != "menu":
            return False
        column, row = self.cursor % 2, self.cursor // 2
        if direction == "l":
            column = 0
        elif direction == "r":
            column = 1
        elif direction == "u":
            row = 0
        elif direction == "d":
            row = 1
        else:
            return False
        cursor = row * 2 + column
        if cursor == self.cursor or cursor >= len(self.moves()):
            return False
        self.cursor = cursor
        self.seq += 1
        return True

    def confirm(self, now):
        """A on the pad: take the highlighted option, or advance the text."""
        if self.phase == "action":
            if ACTIONS[self.cursor] == "RUN":
                return self.try_run(now)
            # FIGHT: open the move list.
            self.phase = "menu"
            self.cursor = 0
            self.next_at = now + MENU_TIMEOUT
            self.seq += 1
            return True
        if self.phase == "menu":
            return self.play(self.cursor, now)
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
        """B on the pad: out of the move list, back to FIGHT/RUN."""
        if self.phase != "menu":
            return False
        self.phase = "action"
        self.cursor = 0
        self.next_at = now + MENU_TIMEOUT
        self.seq += 1
        return True

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
            "actions": list(ACTIONS),
            "runAttempts": self.run_attempts,
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
        "hp": fighter["hp"],
        "maxHp": fighter["maxHp"],
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
