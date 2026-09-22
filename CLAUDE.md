# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An Omarchy (Quickshell/Hyprland) plugin: when a window move collides with
another window, roll 25% and settle it with a turn-based Pokémon-style fight.
Works on any Hyprland layout — dwindle, master, scrolling — and needs no other
plugin. Pure Python 3 stdlib + QML. No build step, no third-party modules.

## Commands

```bash
make check                          # tests + byte-compile + manifest/asset presence + omarchy plugin validate
make test                           # tests only
python3 tests/battles.py Damage                    # one test class
python3 tests/battles.py Eating.test_eating_heals_and_costs_the_turn   # one test
make audio                          # regenerate the committed WAVs (bin/make-battle-audio)
bin/hyprbattles-ctl move left       # move the focused window, roll if it collided
bin/hyprbattles-ctl                 # current battle state as JSON (needs the daemon)
bin/hyprbattles-ctl debug           # force a battle; pick N / advance to drive it
bin/hyprbattles-ctl pantry          # the food shelves, read-only, daemon or not
bin/hyprbattles-ctl roster          # every window as a creature (--json for the panel)
bin/hyprbattles-ctl feed <addr> <shelf>   # one portion, daemon or not
bin/hyprbattles-ctl sleeping        # creatures whose windows are shut
bin/hyprbattles-ctl moves <addr>    # the four carried, and the whole learnset
bin/hyprbattles-ctl teach <addr> <slot> <TYPE:n>   # swap one of the four
bin/hyprbattles-ctl assets          # asset mode + what every sound resolves to
```

Forcing/inspecting through the shell instead of the socket:
`omarchy-shell -q hyprscroll2d-battle debugBattle | cancel`, `omarchy-shell hyprscroll2d-battle shown`.
The bar panel's own views: `omarchy-shell -q hyprbattles-roster open | pantry |
best | food <addr>`.

## Two traps

- **QML does not hot-reload in this shell.** After any `.qml` change, run
  `omarchy restart shell`.
- **This Hyprland is configured in Lua**, and its IPC evaluates
  `hl.dispatch(<what you sent>)`. Classic dispatcher strings are a syntax
  error, and the error comes back in a reply nobody reads — so it looks like
  nothing happened. Everything sent must be an `hl.dsp.*` expression; a test
  pins that.

## Architecture

Three layers, deliberately split so the rules are testable with no compositor,
no pad and no screen:

| Layer | File | Owns |
| --- | --- | --- |
| Rules | `lib/battle_rules.py` | Creatures, types, damage, turn loop, menus, timeouts, and the progression maths - experience, stages, appetite - plus the `Evolution` scene. **Zero I/O.** Emits a snapshot dict after every change. |
| Records | `lib/creatures.py` | What a window class has earned, what one live window has eaten, window uptime and the agent running in a window off `/proc`, and the roster/feed the daemon and the CLI share. The only module here that writes anything but a ledger. |
| Moves | `lib/window_moves.py` | Which command moves a window one cell per layout, and whether a move swapped two windows. **Zero I/O.** |
| Wiring | `bin/battles` (daemon) | Sockets, sound, pad lease, bar toggle, the roll, publishing the snapshot. |
| Picture | `Battle.qml` + `BattleFighter/BattleStatusBox/BattleTypeChip/PixelText.qml` | Draws the snapshot and nothing else. Two scenes: `scene: "battle"` and `scene: "evolve"`. |
| Panel | `Roster.qml` (bar widget) | The switch, one card per window, and the food. Reads `hyprbattles-ctl roster --json`, writes through `hyprbattles-ctl feed`. Cannot reach a window. Agent cards wear Omarchy's own marks (`shell/plugins/agents/assets/*.svg`, then the default-agent menu glyph), which is why the agent names are Omarchy's names. |

Data flow: daemon writes `$XDG_RUNTIME_DIR/hyprscroll2d-battle.json` after every
change → `Battle.qml` watches that file. Input goes the other way: the overlay
holds the keyboard and shells out to `bin/hyprbattles-ctl key <name>`, which talks
to `$XDG_RUNTIME_DIR/hyprscroll2d-battle.sock` (whitespace verb + args in, JSON
state out — `Daemon.handle_command`). Keyboard names map onto forwarded
controller events (`Daemon.KEYS`) so there is one set of handlers, not two.

Other modules: `lib/pantry.py` (the `ITEM` food shelves and their ledger),
`lib/battle_assets.py` (which directory each sound comes from),
`hyprbattles.lua` (a `dofile`-able helper that binds `hyprbattles-ctl move`
to four keys; it may bind that verb and dispatch nothing, which a test pins),
`lib/hyprland.py` (the two Hyprland sockets, shared by the daemon and the CLI
so a move made with the daemon down lands the same way).

### No plugin is required, and none is ever linked

Demon Slayer's Hyprscroll2D (layout) and the gamepad plugin are reached
**only** through Hyprland's own event/command sockets and the gamepad plugin's
unix control socket. Nothing is imported, and neither is looked for on disk —
a missing neighbour costs a shortcut, not an error. In user-facing docs the
layout is always "Demon Slayer's Hyprscroll2D", a **private fork of the
original Hyprscroll2D that is never to be published** (its author's call);
never present it as a dependency.

Two trigger paths, both ending in: switch checked → 25% roll → 6s cooldown.

1. **The one everybody has.** A key bound to `hyprbattles-ctl move <dir>` →
   daemon's `move` verb → window list, dispatch, window list again. Two
   windows trading places is a collision; one window landing in an empty cell
   is not. `lib/window_moves.py` picks the command from `getoption
   general:layout` (`hl.dsp.layout("move left")` for a scrolling layout,
   `hl.dsp.window.move({ direction = "l" })` for everything else) and falls
   back to the other style when the first moved nothing, so a per-workspace
   layout works. The move happens with battles off, on a losing roll, and with
   the daemon stopped — `hyprbattles-ctl` makes it itself then.
2. **The shortcut.** Both plugins post
   `custom>>...:collision,<addr>,<addr>,<dir>` on Hyprland's event socket
   (payload rides inside the event *name*, comma separated, because
   `hl.dsp.event` drops extra arguments). Both are listened for and
   de-duplicated within 0.5s, or d-pad moves would roll twice.

## Invariants that tests enforce — do not break them

- **A battle result may only ever send one `move` command, and it is the
  exact reverse of the move that started the battle** (`self.move_style`, so a
  dwindle swap is not undone with a scrolling layout's message). Never close,
  kill, float, fullscreen or re-workspace a window (`BattleWiring`,
  `AnyLayout`).
- **The pantry is read-only.** A test greps `lib/pantry.py` and fails if a
  shelf ever reaches for a write, an unlink, a signal or a subprocess. It
  reads `/proc` counters and one `statvfs`, never file contents.
- **`lib/battle_assets.py` is the only place that knows the asset resolution
  order**; a test asserts the daemon keeps no copy.
- **Generated audio must stay playable**: not silent, not clipped, short
  enough for a one-shot, and the theme must loop without a click at the seam.
- **A creature's stats and learn order are seeded from its class key, never
  from its address** (`key_seed`). Addresses are handed out fresh on every
  launch, so an address-seeded creature re-rolled itself every restart while
  keeping its level. A shut window has no address at all, which is what the
  sleeping list needs.
- **An appetite outlives the window, and so do the meals**
  (`AnAppetiteThatOutlivesTheWindow`). Both are the class's and both live in
  `creatures.json`: the hours its windows have been open are banked as they
  age (`Store.bank`, `Store.lived`) and eating drains them
  (`Store.consume`), so a reopened window is as hungry as it was left and
  closing a full one is not a second helping. The two move together or one of
  them is a loophole. Nothing accrues while it sleeps, nothing is banked
  twice, and several windows of one class buy one hour an hour between them.
  The per-pid entry left in the file is only the note saying how much of a
  window's age has been counted; it dies with the pid and the hours do not.
- **A creature is its window class, never its address** (`lib/creatures.py`).
  Addresses are recycled; a record kept under one would be lost on restart and
  then inherited by a stranger. So is the roster: every open window of a class
  is **one row** with a `count`, an `instances` list and one appetite that all
  of them eat against, or opening a second window of something would double
  the experience it can be fed (`creatures.stomach`, `TheRoster`). `feed`
  takes the window list to know what the creature is.
- **The one class a window can borrow is the agent running in it.** Claude
  Code and Codex are not windows, and their titles name your work rather than
  themselves, so `AGENT` is found by walking the process tree under a
  terminal's pid (`creatures.agent_of`, comm and cmdline, breadth first and
  bounded) and stamped onto the window as `agent`; `rules.agent_tool` stays
  pure and reads the stamp, falling back to title words for a session over
  ssh. `creatures.species_key` is the one place that stamps, because every
  question about a creature comes through a record first. A terminal is an
  `AGENT` named `claude` while one runs and a `SHELL` named `foot` again
  afterwards, each with its own record. Only a `SHELL` is ever asked (a
  browser on claude.ai is a browser; `org.omarchy.agent` is Omarchy's agent
  launcher, a foot under its own app id, so it counts as a `SHELL`), and
  every tool name must itself read back as `AGENT` through `type_of`, or a sleeping agent - which has nothing left but its key - would
  change type when its window shut. Tests pin both.
- **A creature always carries four moves, at least two of its own type, and
  all of them ones it has learned** (`Learning`). A record that says otherwise
  is ignored in favour of the derived four - `carried()` decides, nothing
  else. The learnset only ever grows with level and stage.
- **Feeding cannot reach a window.** A test greps `lib/creatures.py` and
  `Roster.qml` for `dispatch`, `subprocess`, `hyprctl` and the rest. The panel
  reads the window list and writes a record; that is all it may ever do.
- **An evolution holds nothing and moves nothing** - no pad, no bar, no
  window - and the record is written *before* the animation, so skipping it
  costs only the picture (`Evolving`).
- **Every `Text` in `Roster.qml` is `PlainText`, and only a bound path
  gets a reply.** A window title is whatever the window says (a page's
  `document.title`, a terminal escape), and QtQuick's `Text` defaults to
  AutoText, which turns into an HTML engine at the first tag - an `<img>`
  would have the shell fetch it. The reply-side sockets (`PadLease`,
  `ask()`, `already_running()`) are abstract, so anything local can post
  to them; a datagram from anywhere but the daemon's own bound path is
  dropped unread.
- **The bar icon is never the urgent colour.** On is the bar's own colour, off
  is grey, and the red dot appears only when a creature is one meal on the
  shelves away from evolving - and never while battles are off.
- Nothing can get stuck: text self-advances (1.7s), idle menu gives up (25s),
  hard cap (180s), rule crashes are caught in `tick_battle()`, the overlay has
  its own 2-minute watchdog, and losing the pad lease ends the battle.

## State lives in files, not in the daemon

`~/.local/state/hyprscroll2d/` holds `battles-disabled` (presence = off),
`battles-assets` (the mode), `pantry.json` (the eaten-portions ledger) and
`creatures.json` (what each class has earned, including the hours its windows
have been open and everything it has eaten).
Files, because the Omarchy menu row's `checked` condition and `hyprbattles-ctl`
must answer while the shell is restarting. `hyprbattles-ctl` reads/writes them
directly and only *nudges* the daemon afterwards.

`creatures.json` is also the sleeping list: the daemon writes a record for
every window open at startup and for every `openwindow` event (class taken
from the event payload, no IPC query), so every class the machine has ever
run is on that list once its windows are shut, restarts included.

## Sound and assets

All eight WAVs are synthesised by `bin/make-battle-audio` from the stdlib
`wave` module and committed, so a clone fights with sound and ships nothing
anyone else wrote. **Keep it that way** — no third-party audio, fonts, sprites
or names, and no cover of an existing tune. User music goes *outside* the
checkout, in `$XDG_CONFIG_HOME/omarchy/hyprbattles/assets/`, resolved per
file by mode (`auto`/`generated`/`custom`), overridable for one run with
`HYPRBATTLES_ASSETS`.

## Conventions

- QML colours come from `qs.Commons` (`Color.*`) so battles read on any theme.
  The only hardcoded colours are the eight type colours and the HP bar's
  green/amber/red, which must mean the same thing everywhere.
- Lettering is the original 5×7 font in `PixelText.qml`, drawn square by square
  on a Canvas — no font files.
- `tests/battles.py` loads the extension-less `bin/battles` and `bin/hyprbattles-ctl`
  through `SourceFileLoader`; new executables there need the same treatment.
- Docs carry the reasoning: `docs/BATTLES.md` (rules, trigger, sound, escape
  hatches), `docs/FOOD.md` (the pantry and its ledger), `docs/CREATURES.md`
  (identity, levels, evolution, hunger, the bar panel). Behaviour changes
  belong in them too.
- QML sizes come from `Style.font.*`, which are **pixels**: `font.pixelSize`,
  never `pointSize`, or everything renders a third too big.
- Commit subjects are a sentence, not a conventional-commits prefix
  ("Reap the bar toggles, and correct the sound doc"), and the body explains
  *why*, including the alternatives dropped.
- Some header comments still name files that moved (`Service.qml` mentions a
  `BattlesToggle.qml` that no longer exists; `Battle.qml` names
  `lib/hyprscroll2d_battle.py`). Trust the code, not those paths.
