# Window battles

Throw a window at another window and, one time in four, the two of them settle
it in a turn-based fight instead of just swapping places. On any Hyprland
layout - dwindle, master or scrolling - and with a d-pad or without one. The
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

- battles are **switched on** - the bar widget, or `bin/hyprbattles-ctl on`;
- the move **collided** - it landed on another window and swapped the two,
  rather than stepping into an empty cell;
- the 25% roll came up.

It does not matter what asked for the move. A window thrown with
`SUPER + SHIFT + LEFT` deserves a battle exactly as much as one thrown with the
d-pad, and both are played the same way: the overlay takes the keyboard, and
borrows the controller as well if there is one.

The move itself is never conditional on any of this. `hyprbattles-ctl move` moves
the window with battles switched off, on a losing roll, and with the daemon
stopped - in which case the command makes the move itself rather than asking
for it. A move key that died with the shell would be a far worse bargain than
a missed battle.

The switch is checked before the roll, and it is only a `stat()` on a flag
file, so it costs nothing to check on every collision rather than caching a
value a click could make stale.

There is a six second quiet period afterwards, so a run of collisions cannot
stack battles on top of each other, and a battle can never start another one.

**No layout plugin is required.** The daemon makes the move itself, on
`hyprbattles-ctl move <direction>`, and compares Hyprland's window list either
side of it: two windows standing where the other one was is a collision, one
window in a cell that was empty is not. Dwindle, master and a scrolling layout
therefore collide the same way, and the only thing that differs between them
is which command moves a window one cell - which is all of
`lib/window_moves.py`.

Who was standing where is worked out from window *centres*, not from the gap
between two facing edges. A scrolling layout draws the focused window wider
than its cell, so it laps a couple of hundred pixels over the window beside
it: measured edge to edge that neighbour is behind the focused window, and
edge measurement therefore looked straight past the one window that was
actually in the way. Centres do not care how wide either window was drawn.

**Demon Slayer's Hyprscroll2D** - a private fork of the original Hyprscroll2D,
never to be published, and that is its author's call - announces its own
collisions, so on it the move keys it already binds trigger battles with
nothing rebound. That is a shortcut for one desktop, not a dependency: without
it, bind a key to `hyprbattles-ctl move` and nothing else changes.

**The gamepad plugin is optional.** It adds a controller to play with, the
narrower pad-only collision event, and a second of both motors flat out as a
battle opens - nothing else. Without it, battles still trigger from keyboard
moves and are still fully playable, because the overlay has the keyboard
regardless.

The buzz is asked for over that plugin's control socket
(`rumble 1.00 1.00 1000`, see its `docs/PAD-API.md`) rather than written to
the device: the pad is its to drive, and it caps what a client may ask for.
It goes out even when the lease was refused, because the controller may be
sitting right there whichever hand started the fight, and a buzz costs
nothing when it is not.

## The trigger path

The one everybody has - a key bound to `hyprbattles-ctl move left`:

```
SUPER + SHIFT + LEFT
  -> bin/hyprbattles-ctl move left  ->  the daemon's `move` verb
       -> the window list now
            -> hl.dsp.window.move({ direction = "l" })   (dwindle, master)
               or hl.dsp.layout("move left")             (a scrolling layout)
                 -> the window list again: did two windows trade places?
                      -> bin/battles: switched on? roll 25%
                           -> borrows the controller, if there is one
                                -> lib/battle_rules.py runs the fight
                                     -> $XDG_RUNTIME_DIR/hyprscroll2d-battle.json
                                          -> Battle.qml draws it
```

Which of the two commands goes out is decided by `getoption general:layout`,
and if the first one moves nothing at all the other one gets its turn. That
fallback is what makes a per-workspace layout work: a move message a layout
does not understand is a no-op, and a no-op is visible - nothing on screen
moved - so only one of the two can ever land.

The shortcut, on a desktop that has Demon Slayer's Hyprscroll2D:

```
a d-pad push, or SUPER + SHIFT + LEFT
  -> hl.dsp.layout("move left")
       -> the layout plugin's layout_msg "move"
            -> core.move() returns (true, <the window it displaced>)
                 -> custom>>me.schafman.omarchy.plugin.hyprscroll2d:collision,...
                      -> bin/battles: switched on? roll 25%   (and on as above)
```

Each plugin only knows the next through a public interface. The layout says
*two windows swapped*, and that is the trigger. This plugin decides whether
that is worth a fight, which is the only part that is about battles at all.

Either way a lost battle is undone by the same command that made the move,
run backwards - `hl.dsp.layout("move right")` for a layout message,
`hl.dsp.window.move({ direction = "r" })` for a dispatcher. Undoing a dwindle
swap with a scrolling layout's message would do nothing at all, and quietly.

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
custom>>me.schafman.omarchy.plugin.hyprscroll2d:collision,0x55f1c2,0x55f1d8,left
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
| Name | The window's initial class, uppercased, cut to 12 characters. `org.gnome.Nautilus` fights as `NAUTILUS`, and an evolved one earns a word in front of it. |
| Type | The class, matched against a table of the usual suspects. |
| Level | What the class has earned: meals and battles, remembered across restarts. Everything starts at 5. See [CREATURES.md](CREATURES.md). |
| Stage | The level: 1, then 2 at level 12, then 3 at level 25. It is worth a name, a few points of attack and - the part that matters - better moves. |
| HP, attack, defense, speed | The level and the stage, plus a small fixed spread off the window's address so two creatures of the same level are not the same creature. |
| A sturdiness bonus | The window's area on screen, worth a little HP and defense and nothing else. It used to be the whole level, which was unfair to anyone whose windows cannot be big. |
| Its four moves | The address, and the stage: a stage-1 creature cannot reach its type's strongest move, and a stage-3 one knows all three. |

### Types

Eight, named after what windows do rather than after the elements of any
particular game, arranged in a ring. Each type hits the next one for double and
bounces off the one before it for half:

```
SHELL -> AGENT -> CODE -> NET -> CHAT -> MEDIA -> GAME -> GLASS -> SHELL
```

A ring is easy to hold in your head after two battles, and unlike a
hand-written chart it cannot accidentally produce a type that loses to
everything - each type is weak to exactly one other and resists exactly one.

`SHELL` is terminals, `AGENT` is coding agents and AI apps, `CODE` is editors
and IDEs, `NET` is browsers, `CHAT` is messaging and mail, `MEDIA` is players
and creative tools, `GAME` is games, launchers and engines, and `GLASS` is
every window that is nothing more interesting than a window. Unrecognised
classes are `GLASS`.

The ring puts `AGENT` where it belongs in the argument: the terminal that
hosts it can always pull the plug (`SHELL` beats `AGENT`), and the agent
rewrites the editor's work for it (`AGENT` beats `CODE`).

`AGENT` is the one type that is not read off the class alone. Claude Code,
Codex and the rest are not windows - they run *inside* a terminal, and the
terminal goes on calling itself `foot`. Their titles are no help either:
Claude Code sets the terminal title to a summary of what you are doing
("Sleeping windows persistence"), which names everything except itself.

So for a window that is already a `SHELL`, the **process tree** under its pid
is walked instead (`creatures.agent_of`): breadth first, eight steps down at
most, reading `comm` and `cmdline` - `foot` -> `bash` -> `claude`. A tool
started through an interpreter is found by the path it was given, whole step
by whole step, so `node .../codex/cli.js` is `codex` while the snapshot
directory every shell sources, `~/.claude/shell-snapshots/`, is nothing.
The names known are Omarchy's own, from the menu row that asks you to pick a
default agent - `claude`, `codex`, `copilot`, `crush`, `cursor-agent`,
`gemini`, `grok`, `hermes`, `muse`, `omp`, `openclaw`, `opencode`, `pi` -
plus `aider`, `goose` and `qwen-code`. Taking the desktop's list rather than
inventing one is also what lets the panel draw the desktop's icons (see
[CREATURES.md](CREATURES.md)).

A command-line agent is matched by its **whole** name, never as a substring:
"pi" is inside Epiphany and Pidgin, and an agent called `pi` is the word and
nothing else. Only the desktop apps are matched loosely, by class.

The title is still read, but only as a fallback for a session this machine
cannot see into - an agent over `ssh` has its process tree on the other
machine - and then whole words only, so `vim claude_notes.md` is a terminal
editing a file. Only terminals are asked either way, so a browser tab called
"Claude" is a browser. The desktop apps - Claude, ChatGPT, Codex, Ollama and
friends - announce themselves in their class like everything else, and are
matched before `CODE` and `CHAT` because "codex" contains "code" and
"chatgpt" contains "chat".

A terminal is therefore an `AGENT` while an agent is running in it and a
`SHELL` again when it exits - and it is remembered as the agent, not as the
terminal, so every `claude` session shares one record no matter which
terminal it is in. See [CREATURES.md](CREATURES.md).

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
| D-pad or left stick | Arrows, or `hjkl` | Move the cursor: up/down in `FIGHT`/`ITEM`/`RUN` and the pantry, around the 2x2 move grid |
| `A` | `Z`, `Enter` or `Space` | Take the highlighted option, or show the next line of text |
| `B` | `X` or `Backspace` | Out of the move list or the pantry, or on with the text |
| `Start` / `Select` | `Escape` | Leave, whatever is happening; again on the closing line, go now |

`Z` and `X` sit next to each other under the hand that is not on the arrows,
which is where every handheld emulator puts `A` and `B` - and they are the
pair the on-screen hints name, because a hint has to be one key and not three.

While the controller is borrowed, nothing on it reaches the desktop, so no
stray press can close or throw a window mid-fight. Holding `Guide` still hands
the pad back, because taking the controller off a borrower has to work even
when the borrower is wedged - and losing it that way ends the battle.

The two are one set of controls rather than two that could drift apart: the
keyboard maps onto the forwarded controller events and goes through the same
handlers.

The hints along the bottom name one of the two, never both. The daemon
remembers which was last used to play and publishes it as `input` in the
snapshot; the overlay labels the row from that. Both sets at once was six
labels to read past to find the two that were yours. Either device can take
over mid-fight - the pad is grabbed whoever started the battle, and the
keyboard is never taken away - so the row re-labels itself on the first press
from the other hand.

### Eating

`ITEM` opens the pantry: free memory, page cache, swap, entropy, zombie
processes and whatever is in `/tmp`, read live off the machine you are sitting
at. Feeding heals a fraction of the creature's own maximum HP, and enough of
it levels a creature up mid-battle.

Everything about it is read-only - no memory is freed, no cache dropped, no
process reaped - and a ledger stops you eating the same 512 MiB twice. The
whole of it, including why that is honest rather than a cheat, is in
[`FOOD.md`](FOOD.md).

Eating costs the turn, which is what stops it being strictly better than
fighting.

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

A battle that is over still sits there for a few seconds so its last line can
be read. Pressing the way out again during those seconds takes the screen down
immediately, because somebody reaching for the escape hatch twice has read
enough. The result is applied when the overlay goes either way, so leaving
early cannot change what the battle did.

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
feature on and off, with a tick on the row while it is on. The first thing in
the bar panel is the same switch, and `bin/hyprbattles-ctl on|off|toggle` is the
same switch from a script. All three read and write one file, so none of them
can disagree.

The bar icon came later, and it is not there to report the switch: it is the
way into the roster, where the creatures and the food are. It stays the bar's
own colour whether battles are on or off - grey while off - and lights a small
red dot only when a creature is one meal away from evolving. See
[CREATURES.md](CREATURES.md).

Off is checked before the roll, so a switched-off battle costs one `stat()`
and nothing else - no compositor round trip, no dice. A battle already on
screen ends when it is switched off, rather than being left running by a
switch that says it cannot happen.

The setting lives in `~/.local/state/hyprscroll2d/battles-disabled`, presence
meaning off - the same pattern the minimap's hidden flag and the gamepad's
mode file use. It is deliberately a **file rather than a running process**:
the menu row's `checked` condition has to be able to answer while the shell is
restarting, and turning battles off has to work then too. `hyprbattles-ctl` reads
and writes it directly and only nudges the daemon afterwards, so the switch
never depends on anything being up.

## Sound

`bin/make-battle-audio` generates **all seven sounds**, the looping theme
included, with nothing but the standard library's `wave` module, out of the
voices a 1980s sound chip had: two pulse channels with switchable duty cycles
for the melody and the harmony, a triangle for the bass and the kick, white
noise for the rest of the drums. They are committed, so a fresh clone fights
with sound without running anything - and with nothing in it that anybody else
wrote.

There are two channels. The music channel plays the theme for the length of the
battle and is taken over by the fanfare when it ends; one-shots get a channel
of their own, so a hit lands over the music instead of cutting it off.

| File | When it plays |
| --- | --- |
| `battle-theme.wav` | Looping, for the length of the battle |
| `battle-select.wav` | Every menu press that did something |
| `battle-hit.wav` | Every time a creature is struck |
| `battle-heal.wav` | A creature is fed |
| `battle-levelup.wav` | A creature grows a level, and on a win |
| `battle-victory.wav` | The challenger won |
| `battle-defeat.wav` | The challenger lost |

The daemon asks for those **names** and never for a path; a missing file simply
means that sound does not play, and everything else still works.

### The theme

Eighteen bars in A minor at 152 beats to the minute, mono, 22 kHz, about
twenty-eight and a half seconds. Two bars of intro flourish - a hammered A/G#
trill, a run up the triad, a crash - then an eight-bar A section of sixteenths
over `i - VI - VII`, then an eight-bar B section that climbs to A6 and walks a
scale back down. Underneath, a triangle bass on eighths, chord stabs on the
offbeats in the second pulse voice, and a kick/snare/hat pattern with a fill
into the top of the loop.

The last bar is the dominant and the intro opens over the tonic, so the end of
the file is a cadence into its own beginning: the loop point is a bar line
rather than a fade, and both ends are taken to silence so the seam cannot
click. The theme is normalised several dB below the one-shots, because both
channels go through the same player at the same volume and a hit has to land
over it.

The era, the instruments, the tempo and the mood are imitated on purpose. The
tune is not: every note of it was written for this repository, and a test
pins the loop, the levels and the lengths down so a bad regeneration cannot
ship silence.

### Your own files instead

Any of the seven can be replaced without touching the repository. Drop a file
of the same name into

```
~/.config/omarchy/hyprbattles/assets/
```

(`$XDG_CONFIG_HOME` is respected). That directory is deliberately **outside the
checkout**: a clone stays clean and `git status` stays quiet however much music
ends up in it, whatever its licence says.

Which of the two directories wins is a mode:

| Mode | What plays |
| --- | --- |
| `auto` | Your file when there is one, the generated one when there is not. Decided **per file**, so replacing only the theme leaves the other six alone. The default. |
| `generated` | Only what ships, even with your files sitting right there. The A/B position: it needs nothing moved. |
| `custom` | Only your files. A name you have not supplied is silent, which is what makes this a real test of your own set rather than a second `auto`. |

```bash
bin/hyprbattles-ctl assets                  # the mode, and what every sound
                                            # is actually resolving to
bin/hyprbattles-ctl assets generated        # A/B against what ships
bin/hyprbattles-ctl assets auto             # back to the default
HYPRBATTLES_ASSETS=custom bin/hyprbattles-ctl assets   # one run only
```

The mode is a file, `~/.local/state/hyprscroll2d/battles-assets`, the same
shape as the on/off flag beside it, so it reads and writes with the shell down.
`HYPRBATTLES_ASSETS` overrides it for one process. The daemon resolves on
every `play()`, so a change lands on the next sound rather than on the next
restart.

The listing is the point of the command. "My file is not playing" has three
ordinary causes - the mode is `generated`, the name is not one the daemon ever
asks for, or the file is not where it needs to be - and all three are visible
in the same three columns:

```
mode       auto
generated  .../plugins/dev.cstav.omarchy.plugin.hyprbattles/assets
custom     /home/you/.config/omarchy/hyprbattles/assets

battle-theme.wav    custom     /home/you/.config/omarchy/.../battle-theme.wav
battle-select.wav   generated  .../assets/battle-select.wav
...
```

`bin/import-battle-theme <file>` decodes anything `ffmpeg` can read into that
directory, for a theme that arrives as an MP3 - the players only understand
PCM. The whole of the resolution order is
[`lib/battle_assets.py`](../lib/battle_assets.py), and nothing else in the
plugin knows about it.

What you put there, and whether you have the right to, is between you and
whoever wrote it; nothing under that directory can reach the repository.

Healing has a sound because it has a mechanic: `battle-heal.wav` plays when a
creature is fed from the pantry, and `battle-levelup.wav` when a meal takes it
up a level. There is still no PP - moves have power and accuracy but unlimited
uses - so nothing would ever play a "PP restore", and there is no such file.

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
light desktop and a dark one. The accents are the eight type colours and the
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
bin/hyprbattles-ctl move left  # move the focused window and roll for a battle
bin/hyprbattles-ctl            # the battle on screen, as JSON
bin/hyprbattles-ctl cancel     # flee it, or close an already-over one (Escape)
bin/hyprbattles-ctl stop       # tear it down now, without the closing line
bin/hyprbattles-ctl debug      # force one
bin/hyprbattles-ctl on|off|toggle
bin/hyprbattles-ctl enabled    # true / false
bin/hyprbattles-ctl assets [auto|generated|custom]
bin/hyprbattles-ctl pick [n]   # play move n
bin/hyprbattles-ctl advance    # step the text on
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
AnyLayout     the move commands, spotting a swap, and the layout fallback
Readings      the /proc parsers, against fixtures and against this machine
TheLedger     regeneration, persistence, and a corrupt file
ThePantry     live readings minus the ledger, and that the machine never moves
Eating        the ITEM menu, healing, levelling, and the turn it costs
CollisionGate the switch, the cooldown, the roll, and nonsense payloads
BattleInput   forwarded controller events, including losing the pad mid-fight
Music           the player, missing files, and that the three name lists agree
Assets          the resolution order in all three modes, per-file fallback,
                the environment override, and that the daemon has no copy of it
GeneratedAudio  that what ships is a playable WAV, is neither silent nor
                clipped, is short enough for a one-shot, and loops without a
                click at the seam
```
