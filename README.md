# Window Battles

Throw a window at another window - with a controller or with the keyboard -
and, one time in four, the two of them settle it in a turn-based fight instead
of just swapping places.

Types, HP bars, a move menu, a `FIGHT`/`RUN` choice, chiptune - and the
fighters are the windows themselves, still running, captured onto a battle
screen over your own wallpaper. The winner keeps the cell they were arguing
about.

It is a joke that plays straight. The type chart is real, the damage formula
is real, the loser genuinely gets moved. What it cannot do is cost you
anything: no window is ever closed, killed, floated, resized or sent
elsewhere. The worst outcome of a battle is a window ending up one cell from
where you wanted it, which is also the worst outcome of not having a battle.

## What it adds

| Piece | What it is |
| --- | --- |
| [`bin/battles`](bin/battles) | The daemon: watches for a pad-driven collision, rolls the odds, borrows the controller, runs the fight. |
| [`bin/battles-ctl`](bin/battles-ctl) | Read the state, switch battles on or off, or force one, from anywhere. |
| [`lib/battle_rules.py`](lib/battle_rules.py) | The rules: creatures, types, damage, the turn loop. No I/O in it at all. |
| [`Battle.qml`](Battle.qml) | The battle screen. Draws the snapshot the daemon publishes, and nothing else. |
| [`PixelText.qml`](PixelText.qml) | An original 5x7 pixel font, drawn square by square onto a Canvas. |

Full rules, the trigger path, the escape hatches and how to force one:
[`docs/BATTLES.md`](docs/BATTLES.md).

## What it needs

Two other plugins, neither of them required and neither of them linked
against:

| For | Interface | Required |
| --- | --- | --- |
| Windows colliding at all, and undoing a swap | The Hyprscroll2D layout's `layoutmsg` dispatcher and its `custom>>` collision event | yes |
| Playing a battle with a controller | The gamepad plugin's lending API (`grab` / `renew` / `release`) | no |
| Knowing a collision was the pad's | The gamepad plugin's own `custom>>` collision event | no |

Everything goes through Hyprland's own sockets, so a missing neighbour means
no battles rather than an error. The gamepad plugin is **optional**: without
it, battles still trigger from keyboard moves and are fully playable, because
the overlay holds the keyboard regardless. Both of its interfaces are
documented in its `docs/PAD-API.md`.

Requirements: Python 3, no third-party modules. An audio player (`mpv`,
`pw-play`, `paplay` or `aplay`) is optional; without one, battles are silent.

## Install

```bash
omarchy plugin add <this repository> --enable
omarchy restart shell
```

Then add the toggle to `~/.config/omarchy/extensions/omarchy-menu.jsonc`:

```jsonc
"trigger.toggle.window-battles": {"icon":"\udb81\udf87","label":"Window Battles","aliases":["battles","pokemon"],"when":"test -x $HOME/.config/omarchy/plugins/dev.cstav.omarchy.plugin.pokemon-battles/bin/battles-ctl","checked":"[ \"$($HOME/.config/omarchy/plugins/dev.cstav.omarchy.plugin.pokemon-battles/bin/battles-ctl enabled)\" = true ]","action":"$HOME/.config/omarchy/plugins/dev.cstav.omarchy.plugin.pokemon-battles/bin/battles-ctl toggle"},
```

It lands under **Trigger -> Toggle**, beside the other switches, with a tick
while battles are on. A toggle is the right shape for this: it is a setting
you flip now and then, not a thing to watch, and a bar icon would spend all
day telling you something you already know.

## Turning it off

The menu row, or:

```bash
bin/battles-ctl off        # or on, or toggle
bin/battles-ctl enabled    # true / false
```

Off means no battle can start at all - it is checked before the roll - and a
battle already on screen ends when it is switched off.

The setting is a **file**, `~/.local/state/hyprscroll2d/battles-disabled`
(present means off), not a running process. Reading and flipping it therefore
works with the daemon stopped, which is what lets the menu row answer while
the shell is restarting. The daemon is only nudged afterwards, so that a
battle already on screen can be ended.

## Development

```bash
make check      # tests, byte-compile, plugin validate
make audio      # regenerate the committed chiptune
```

The rules are pure functions and a state machine with no I/O in them, so the
type ring, the damage formula, the odds, the run chances, the menus and every
timeout run against fixtures with seeded generators. The daemon's judgement
calls - does this collision become a battle, does the switch stop it, what may
a result do to a window - are tested against a bare instance, without a
compositor. [`tests/battles.py`](tests/battles.py).

Two traps worth knowing:

- **QML does not hot-reload in this shell.** After any `.qml` change, run
  `omarchy restart shell`.
- **This Hyprland is configured in Lua**, and its IPC evaluates
  `hl.dispatch(<what you sent>)`. Classic dispatcher strings are a syntax
  error, and over the socket that error comes back in a reply nobody reads, so
  it looks like nothing happened. Everything this daemon sends is an
  `hl.dsp.*` expression, and a test pins that down.

## Licensing

Everything shipped here is original. The chiptune is generated by
[`bin/make-battle-audio`](bin/make-battle-audio) out of the standard library's
`wave` module; the pixel font is drawn glyph by glyph in `PixelText.qml`; the
creature names are your own window classes. No sprites, audio, fonts or names
from any commercial game.

The looping battle theme is deliberately **not** in this repository. The
daemon plays whatever sits at `assets/battle-theme.wav` and knows nothing else
about it; a missing file simply means a quieter battle. What you put there,
and whether you have the right to, is your business - `.gitignore` keeps it
out of the repository either way.

## License

MIT
