# Window battles

Throw a window at another window with the d-pad and, one time in four, the two
of them settle it in a turn-based fight instead of just swapping places. The
windows themselves are the fighters - the real, live, still-running windows,
captured onto a battle screen over your own wallpaper - and the winner keeps
the cell they were arguing about.

It is a joke that plays straight. The type chart is real, the damage formula is
real, the loser genuinely gets moved. What it cannot do is cost you anything:
no window is ever closed, killed, floated, resized or sent to another
workspace. The worst outcome of a battle is a window ending up one cell from
where you wanted it, which is also the worst outcome of not having a battle.

## When it happens

Three things have to be true:

- battles are **switched on** - the bar widget, or `bin/battles-ctl on`;
- the move **collided** - it landed on another window and swapped the two,
  rather than stepping into an empty cell;
- the 25% roll came up.

It does not matter what asked for the move. A window thrown with
`SUPER + SHIFT + H` deserves a battle exactly as much as one thrown with the
d-pad, and both are played the same way: the overlay takes the keyboard, and
borrows the controller as well if there is one.

The switch is checked before the roll, and it is only a `stat()` on a flag
file, so it costs nothing to check on every collision rather than caching a
value a click could make stale.

There is a six second quiet period afterwards, so a run of collisions cannot
stack battles on top of each other, and a battle can never start another one.

The Hyprscroll2D layout plugin is what makes windows collide at all, so
without it there are simply no battles. Nothing errors; moves just swap
windows the way they always did.

**The gamepad plugin is optional.** It adds a controller to play with, and the
narrower pad-only collision event - nothing else. Without it, battles still
trigger from keyboard moves and are still fully playable, because the overlay
has the keyboard regardless.

## The trigger path

```
a d-pad push, or SUPER + SHIFT + H
  -> hl.dsp.layout("move left")
       -> the layout plugin's layout_msg "move"
            -> core.move() returns (true, <the window it displaced>)
                 -> custom>>io.github.kirollosatef.hyprscroll2d:collision,...
                      -> bin/battles: switched on? roll 25%
                           -> borrows the controller, if there is one
                                -> lib/battle_rules.py runs the fight
                                     -> $XDG_RUNTIME_DIR/hyprscroll2d-battle.json
                                          -> Battle.qml draws it
```

Each plugin only knows the next through a public interface. The layout says
*two windows swapped*, and that is the trigger. This plugin decides whether
that is worth a fight, which is the only part that is about battles at all.

The gamepad plugin posts a narrower version of the same thing - the same
collision, but only when the **pad** caused it, which only it can know. That
one is listened for too, so a battle knows it was pad-driven, and the pair is
de-duplicated on the payload: for a d-pad move both arrive, and whichever
lands first is the one that rolls. Rolling on each would quietly double the
odds for d-pad moves only.

The layout plugin announces the collision as a **custom event on Hyprland's own
event socket** rather than as a new IPC call or another file to watch. Three
reasons, and they are the reason the alternatives were dropped:

- both readers already have that socket open - the daemon reads `socket2`
  directly for focus changes, and Quickshell surfaces the same line as
  `Hyprland.rawEvent` - so nothing new has to be opened, polled or watched;
- an event nobody is listening for costs one dispatch and changes nothing, so
  the layout plugin does not care whether this plugin is installed;
- neither plugin has to know where the other one lives on disk.

A file in `$XDG_RUNTIME_DIR` would have needed a watch and a way to tell a new
collision from a repeated one; a `hyprscroll2d` IPC call would have made the
layout plugin depend on the shell being up, and on this plugin's target name.
The workspace-blocks plugin in this setup publishes its own moves the same way.

One wrinkle: `hl.dsp.event` takes only the event name and drops any further
arguments, so the payload rides inside the name, comma separated. On the socket
it arrives as:

```
custom>>io.github.kirollosatef.hyprscroll2d:collision,0x55f1c2,0x55f1d8,left
custom>>dev.cstav.omarchy.plugin.hyprscroll2d-gamepad:collision,0x55f1c2,0x55f1d8,left
```

The two fields are Hyprland window addresses - the same ones `hyprctl clients`
prints - so a reader can look both windows up without asking the layout plugin
anything.

The gamepad daemon only re-posts a collision if the pad asked for a move in
the last 1.2 seconds, which is how "was this the pad" gets answered at all.

## The creatures

Everything about a fighter comes from the window, so the same two windows
always meet as the same two creatures.

| Part of the creature | Comes from |
| --- | --- |
| Name | The window's initial class, uppercased, cut to 12 characters. `org.gnome.Nautilus` fights as `NAUTILUS`. |
| Type | The class, matched against a table of the usual suspects. |
| Level | The window's area on screen. Screen real estate is the only currency a window has. |
| HP, attack, defense, speed | The window's address, which is stable for as long as the window is. |
| Its four moves | The address again: two of its own type, two borrowed. |

### Types

Seven, named after what windows do rather than after the elements of any
particular game, arranged in a ring. Each type hits the next one for double and
bounces off the one before it for half:

```
SHELL -> CODE -> NET -> CHAT -> MEDIA -> PIXEL -> GLASS -> SHELL
```

A ring is easy to hold in your head after two battles, and unlike a
hand-written chart it cannot accidentally produce a type that loses to
everything - each type is weak to exactly one other and resists exactly one.

`SHELL` is terminals, `CODE` is editors and IDEs, `NET` is browsers, `CHAT` is
messaging and mail, `MEDIA` is players and creative tools, `PIXEL` is games and
launchers, and `GLASS` is every window that is nothing more interesting than a
window. Unrecognised classes are `GLASS`.

### Damage

The familiar shape - level and power on top, the defender's defense underneath,
a small random spread so a matchup is never quite the same fight twice:

```
damage = ((2 x level / 5 + 2) x power x attack / defense) / 50 + 2
         x type effectiveness      (2, 1 or 0.5)
         x 1.5 if the move matches the attacker's own type
         x 1.5 on a critical hit  (1 in 16)
         x 0.85 .. 1.00
```

with a floor of 1, so no attack is ever pointless. HP is deliberately roomy:
a fight that ends in three hits is over before the HP bar has finished moving,
and the bar is half the fun. Expect six to ten turns.

Every roll comes from a generator seeded from both window addresses, so a
rematch between the same two windows is recognisable without being identical.

## Playing it

Either hand. The battle screen holds the keyboard the whole time - which is
also what makes the two windows inert while they fight - and borrows the
controller as well when one is there.

| Controller | Keyboard | What it does |
| --- | --- | --- |
| D-pad or left stick | Arrows, or `hjkl` | Move the cursor: up/down in `FIGHT`/`RUN`, around the 2x2 move grid |
| `A` | `Enter` or `Space` | Take the highlighted option, or show the next line of text |
| `B` | `Backspace` | Out of the move list back to `FIGHT`/`RUN`, or on with the text |
| `Start` / `Select` | `Escape` | Leave, whatever is happening |

While the controller is borrowed, nothing on it reaches the desktop, so no
stray press can close or throw a window mid-fight. Holding `Guide` still hands
the pad back, because taking the controller off a borrower has to work even
when the borrower is wedged - and losing it that way ends the battle.

The two are one set of controls rather than two that could drift apart: the
keyboard maps onto the forwarded controller events and goes through the same
handlers.

### Running away

`RUN` **always works before the first blow is struck.** Walking into something
and immediately thinking better of it should never be punished.

Once you have actually swung at it, leaving is a gamble. Faster creatures get
away more often, and each failed attempt improves the next one, so the odds run
from 20% to 95%; a failed attempt costs you the turn and the other window gets
a free hit. That makes `RUN` a real decision rather than a free exit.

None of that applies to `Start`, `Select` or `Escape`. Those end the battle
outright, every time, whatever the odds would have said. They are the escape
hatch, and an escape hatch with a dice roll on it is not one.

## What a result does

| Result | What happens to the windows |
| --- | --- |
| The challenger wins | Nothing. The swap already happened when the move landed, so it is already standing on the contested cell. |
| The challenger loses | The same swap, run backwards - one `move` layout message in the opposite direction. |
| Fled, cancelled, or timed out | Nothing. The move stands, exactly as it would have without a battle. |

That is the entire list. `end_battle()` in `bin/gamepad` may send one `move`
message and nothing else, and a test asserts that it never learns to close,
kill, float, fullscreen or re-workspace anything.

## Nothing can get stuck

A battle is an overlay that holds the keyboard, so every way it can end is
worth knowing about:

- **the text advances itself** after 1.7 seconds a line, so it cannot wait for
  a button that is never pressed;
- **an idle menu gives up** after 25 seconds and leaves as a draw;
- **a hard cap of three minutes** ends any battle, whatever else is happening;
- **a crash in the rules** is caught in `tick_battle()`, logged, and treated as
  the battle ending - it cannot take the daemon down with it;
- **the overlay has its own watchdog**: if the daemon stops publishing for two
  minutes while a battle is up, `Battle.qml` drops the keyboard by itself,
  without waiting to be told;
- **losing the controller ends it**: if the lease is revoked - the gamepad
  daemon stopped, the focused window took the pad back, or a renewal lapsed -
  there is no way left to play, so the battle leaves rather than sitting there;
- **the daemon's shutdown** stops the music, gives the pad and the bar back and
  deletes the state file, so disabling the plugin or restarting the shell ends
  any battle;
- **a daemon that was killed outright** cannot run its shutdown, so the next
  one sweeps up after it: stray players are killed, and a stale state file
  saying a battle was running is taken as evidence that the bar needs bringing
  back.

## The switch

**Trigger -> Toggle -> Window Battles** in the Omarchy menu turns the whole
feature on and off, with a tick on the row while it is on.
`bin/battles-ctl on|off|toggle` does the same from a script.

A toggle rather than a bar icon, because that is what this is: a setting you
flip now and then, not a thing to watch. A bar icon would spend all day
reporting a state that changes twice a month.

Off is checked before the roll, so a switched-off battle costs one `stat()`
and nothing else - no compositor round trip, no dice. A battle already on
screen ends when it is switched off, rather than being left running by a
switch that says it cannot happen.

The setting lives in `~/.local/state/hyprscroll2d/battles-disabled`, presence
meaning off - the same pattern the minimap's hidden flag and the gamepad's
mode file use. It is deliberately a **file rather than a running process**:
the menu row's `checked` condition has to be able to answer while the shell is
restarting, and turning battles off has to work then too. `battles-ctl` reads
and writes it directly and only nudges the daemon afterwards, so the switch
never depends on anything being up.

## Sound

`bin/make-battle-audio` generates the hit and the two fanfares with nothing but
the standard library's `wave` module, out of the voices a 1980s sound chip had:
a pulse channel with a switchable duty cycle for the melody, a triangle for the
bass, white noise for the drums. They are committed, so a fresh checkout has
audio without running anything.

There are two channels. The music channel plays the theme for the length of the
battle and is taken over by the fanfare when it ends; one-shots get a channel
of their own, so a hit lands over the music instead of cutting it off.

| File | When it plays |
| --- | --- |
| `assets/battle-theme.wav` | Looping, for the length of the battle |
| `assets/battle-select.wav` | Every menu press that did something |
| `assets/battle-hit.wav` | Every time a creature is struck |
| `assets/battle-victory.wav` | The challenger won |
| `assets/battle-defeat.wav` | The challenger lost |

The daemon plays whatever sits at those paths and knows nothing else about
them, so swapping one out is a supported thing to do, and a missing file simply
means that sound does not play - everything else still works.

The looping theme is **not** in this repository. What you put there, and
whether you have the right to, is your business; keep the `.gitignore` entry
that stops it being committed, and do the same for anything else you drop in.

There is no PP and there is no healing, so there is nothing for a
"PP restore" or "HP restore" sound to play on. Moves have power and accuracy
but unlimited uses, and no creature ever gains HP back during a fight. Adding
either would mean adding the mechanic first - an item menu beside `FIGHT` and
`RUN`, and longer battles to go with it - which is a bigger change than a
sound file.

The player is the first of `mpv`, `pw-play`, `paplay` and `aplay` that is
installed. With none of them, battles are silent rather than refused.

## Looking at it

The screen is [`Battle.qml`](../Battle.qml), and it only draws - every rule
lives in [`lib/battle_rules.py`](../lib/battle_rules.py), which
publishes a snapshot to `$XDG_RUNTIME_DIR/hyprscroll2d-battle.json` after every
change. That split is why the rules can be tested without a screen, and why a
mistake in the drawing cannot reach a window.

The fighters are live [`ScreencopyView`](../BattleFighter.qml)s of the two
toplevels, so a terminal keeps scrolling and a video keeps playing while it is
being attacked. Nothing is moved or re-parented to put them there.

The lettering is an original 5x7 pixel font in [`PixelText.qml`](../PixelText.qml),
drawn square by square onto a Canvas. This machine has no scalable pixel font -
the `.fon` bitmaps installed here render at one fixed size - and a font drawn
in QML is crisp at any size, scales with the monitor instead of with fontconfig,
and carries no licence. Lowercase is folded to uppercase on the way in, the way
the machines this is imitating did.

Everything but the deliberate accents comes from the theme, so it reads on a
light desktop and a dark one. The accents are the seven type colours and the
green/amber/red of the HP bar, which have to mean the same thing everywhere.

The bar is hidden for the length of the battle and comes back afterwards -
unless you already had it hidden, in which case it is left alone.

## Forcing one

Waiting for a 25% roll is no way to work on a battle screen.

```bash
omarchy-shell -q hyprscroll2d-battle debugBattle   # focused window vs its neighbour
omarchy-shell -q hyprscroll2d-battle cancel        # end the one on screen
omarchy-shell hyprscroll2d-battle shown            # true / false
```

A forced battle passes no direction, so there is nothing to put back when it
ends: it cannot move anything whichever way it goes. It also works without a 2D
workspace and without a pad plugged in.

From a script, or to drive one without a controller:

```bash
bin/battles-ctl            # the battle on screen, as JSON
bin/battles-ctl cancel     # flee it (what Escape does)
bin/battles-ctl stop       # tear it down now, without the closing line
bin/battles-ctl debug      # force one
bin/battles-ctl on|off|toggle
bin/battles-ctl enabled    # true / false
bin/battles-ctl pick [n]   # play move n
bin/battles-ctl advance    # step the text on
```

`pick` and `advance` are debug aids for exactly one job: taking a screenshot
of a battle in a particular state without a controller in your hands.

## IPC target

`hyprscroll2d-battle`. The other two targets in this pair of plugins,
`hyprscroll2d` and `hyprscroll2d-gamepad`, were taken, and an `IpcHandler`
target has to be unique across the whole shell process - a second handler on an
existing target is silently ignored.

## Tests

`make check`. The rules are pure functions and a state machine with no I/O in
them, so the type ring, the damage formula, the 25% roll, the run odds, the
menus and every timeout run against fixtures with seeded generators:

```
Types         the ring, the class table, and that no type loses to everything
Creatures     determinism, levels, move lists, and windows with nonsense in them
Damage        the floor, type effectiveness, defense, the same-type bonus
Trigger       that the odds really are one in four, over 20000 rolls
TurnLoop      the menus, the phases, the timeouts, the snapshot's shape
Running       free before the first blow, a gamble after it, hatches unaffected
BattleWiring  that a result can still only ever ask for a move
CollisionGate the switch, the cooldown, the roll, and nonsense payloads
BattleInput   forwarded controller events, including losing the pad mid-fight
Music         the player, missing files, and that every asset named exists
```
