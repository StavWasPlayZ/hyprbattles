# Creatures

A battle is something that happens *to* you. This is the other half: the
windows you keep open are creatures that remember what they have been through,
and you can make one stronger on purpose.

Three things are new here, and they fit together: a creature has a **record**
that outlives its window, **feeding** from the bar panel is how that record
grows, and a window's **age** is what limits how much it can eat in a day.

## Who a creature is

A creature is a **window class**, not a window.

That is the only identity a window has that can outlive it. Hyprland
addresses die with the window and are handed out again to whatever opens next,
so a level kept under an address would be lost every time you restarted
Firefox - and then inherited by something that never earned it. The class -
`initialClass`, the name the window was launched under - survives closing,
reopening and rebooting.

It is also deliberately the *launch* class rather than the live one, so a
browser that renames itself after the site it is showing is still the same
creature at teatime as it was at breakfast.

The honest consequence: **every window of a class is the same creature.** Two
terminals are one creature open twice, the way two of the same monster are
the same monster. Feeding one feeds "terminals". If that ever stops feeling
right, the thing to change is this paragraph, not the storage.

Its stats hang off that key too. They used to hang off the address, and that
was wrong in a way only records-outliving-windows could expose: a creature
kept its level across a restart and re-rolled its attack, its HP and the order
it learns moves in, because Hyprland had handed it a new address. A class does
not change, so now none of them do.

Records live in `~/.local/state/hyprscroll2d/creatures.json`, next to the
pantry's ledger and the on/off flag, for the same reason those are files:
`battles-ctl` has to be able to answer while the shell is restarting.

## Levels

Levels are **earned**, and they used to be measured.

The old rule was that a window's level was its area on screen. It read well
and it was unfair: a window that cannot be fullscreened, a laptop panel next
to a 4K monitor, and two layouts that tile differently all handed out levels
nobody had anything to do with. Size is still worth something - a roomier
window is sturdier, worth a little HP and defense - but it is a bonus of at
most 12 points now, not the whole creature.

What buys a level is experience, from two places:

| Source | Worth |
| --- | --- |
| A meal | twice the food's nourishment - a portion of FREE RAM is 68 |
| Winning a battle | 20 + 6 per level of what you beat |
| Losing a battle | 5 + 1 per level of what beat you |
| Fleeing | nothing, the way walking away always has meant nothing |

Every creature starts at level 5. The first level up costs 40, and each one
after it costs 20 more than the last, so the ladder gets slower rather than
stopping - and it does stop, at level 50.

Losing pays, a little. A creature that only ever gets thrown at things it
cannot beat should still creep upwards, or the windows you fight with become
the windows you stop using.

## Evolution

At level 12 a creature evolves, and again at level 25. It is automatic: cross
the threshold and it happens, whether the level came from a meal or a win.

Evolving does three things:

- **A name.** The window keeps its own - it is still your terminal - and earns
  a word in front of it, drawn from what its type is good at: `FOOT` becomes
  `SUPER FOOT` and then `ROOT FOOT`, `FIREFOX` becomes `FAST FIREFOX` and then
  `HYPER FIREFOX`. Nothing in that table is borrowed from anybody's monsters.
- **Stats.** Three points of attack per stage, on top of what the level is
  already worth.
- **Moves, which is the part worth having.** Each type has three moves listed
  weakest first. A stage-1 creature is not allowed the last of them - a
  beginner does not open with the 85. Stage 2 unlocks it. Stage 3 knows all
  three of its own type and borrows only once, so an evolved creature fights
  *differently*, not merely harder: it is the same-type bonus nearly every
  turn, against a shallower answer to a bad matchup.

It happens **on screen**. A level that goes up inside a file nobody opens is
not a reward, so the overlay borrows the arena for about eight seconds: the
window itself in the middle, a flash that quickens, and the new name. Escape
skips it. The record is written *before* the picture starts, so skipping it
can only ever cost you the picture.

An evolution is not a battle. It holds no pad, hides no bar, and cannot send
a window anywhere - a test reads the daemon's `evolve()` and fails if it ever
learns how.

## Sleeping windows

Closing a window does not end its creature; it puts it down. The record is
still there, so the panel lists them - at the bottom of the windows, under
**Sleeping windows**, most recently open first.

A sleeping creature keeps everything it earned: its level, its stage, its
record, its meals and its moves. What it does not have is an **appetite**,
and that is not a rule imposed on it - appetite is bought from
`/proc/<pid>` uptime, and a shut window has no process to buy it with. There
is nothing there to be hungry. Feeding says so and costs nothing.

Its **moves can still be changed**, for the same structural reason: moves
belong to the class, not to the process. Picking a loadout for something you
are about to open is the one thing this screen is actually for.

**Nothing happens while it sleeps**, on purpose. Every other number in this
plugin is a reading of something real - uptime, free memory, dead processes -
and a closed window produces nothing real to read. Idle gains would be the
first invented number in the game.

```bash
battles-ctl sleeping                     # the ones whose windows are shut
battles-ctl moves kitty                  # they answer to their class name
battles-ctl teach kitty 3 NET:0          # and can still be given a loadout
```

## Moves

Four moves are carried. More than four are known, and which four is yours to
decide - the one thing in this plugin you choose rather than earn.

**What it knows.** Its own type's three moves arrive with evolution, exactly
as before: stage 1 reaches the first two, stage 2 the third. Everything else
is borrowed, one move at a time, at **levels 8, 13, 18, 24 and 30** - which is
what a level between two evolutions is for. Before this, a level was three
numbers going up and nothing to decide.

The order is the creature's own. It comes off the same address seed the stats
do, so your terminal always learns the same things in the same order and no
two classes have the same list. The two it was born borrowing come first, so
a creature always knows the moves it is already carrying.

**One rule on the four.** At least two of them have to be its own type. It is
the floor that keeps the type ring meaning something: without it every
creature ends up carrying four 85s and a matchup stops being a thing you play
around. The same-type bonus makes its own moves attractive anyway; the floor
only rules out the degenerate version.

A set that is not a real choice - too few, too many, the same move twice, one
it has not learned, one that was never on its list - is ignored and the
creature fights with the four it would have had anyway. A hand-edited record
costs a preference, never a fighter.

**In the panel.** A window's page lists its four; click one and the whole
learnset opens on that slot, locked moves included with the level they arrive
at. Click a move to read it out in the tip - type, power, accuracy - and the
button along the bottom puts it in the slot. Nothing is swapped by the click
that selected it.

**From the command line.**

```bash
battles-ctl moves <address>                 # the four, then everything known
battles-ctl teach <address> <slot> NET:0    # slot 0-3, move as TYPE:index
```

A refusal is a sentence, not an error: *FOOT learns DNS FLOOD at level 8*,
*It has to keep 2 moves of its own type*.

Moves belong to the class, like levels. Teaching `foot` something leaves
`kitty` alone - they are different creatures that happen to share a type -
but every `foot` window fights with it, and so does the one you throw a window
at.

## Hunger

How much a window can eat is bought with **how long it has been open**.

A window opened a minute ago is a hatchling with an appetite of 20. It gains
18 more per hour it stays up, to a maximum of 200. Eating fills that up;
nothing empties it again except closing the window, which is not a loophole -
that really is a new window, with a new appetite and none of the old one's
meals.

Uptime comes off `/proc/<pid>/stat`, not out of anything this plugin wrote
down. That matters: restarting the daemon, deleting the ledger or editing the
records by hand cannot make a window older than it is.

So there are two independent gates on feeding, and they fail differently:

- **The machine has to have the food spare** - the pantry and its ledger, see
  [FOOD.md](FOOD.md).
- **The window has to have room for it** - its appetite.

Which is what stops a panel with a feed button from being a level button. You
cannot feed a fresh window into a monster; you have to leave it open.

## The bar panel

One icon in the bar - the same crossed swords the Omarchy menu row carries,
so the two ways to the switch look like the same thing. It is **never the
urgent colour**: an icon that goes red for a state you chose cries wolf all
day. On is the bar's own colour, off is grey, and the only thing that ever
stands out is a small red dot, which appears when - and only when - a creature
is **one meal on the shelves right now** away from evolving. Switch battles
off and the dot goes with them; a game that is not running has nothing to ask
for.

Behind the icon are three views, because each is a panel's worth on its own:

**The windows.** The switch first - it is what somebody opening the panel in a
hurry came for - then a card per open window, hungriest first. Each card
carries the application's own icon, the type as its colour, the name, a star
per evolution, the level, the record, how long the window has been up, how far
it is from the next level, and a bar for how much appetite it has left. The
icon is looked up the way the rest of the shell looks one up - the desktop
entry for the class, then the class as an icon name - and a window that has
none simply shows its type chip, as it did before. On the right of each card is the
one action a card has: **Feed**. The button is plain on every card - the type
colour means "what this window fights as", and a button wearing it would be
saying something it does not mean.

The panel calls them windows, not creatures. On screen they are a list of
things you already know by name, and "creature" would be asking you to hold
two names for one thing; the game's word stays in the code and in these docs,
where it is about the fighter rather than about the row.

**The food picker.** Feed opens the pantry *for that window*, with the
window's own card pinned above it - the list is long enough to scroll, and a
window is easy to lose track of halfway down somebody else's dinner. Below it:
every shelf, what it is worth in nourishment, and what the machine has spare.
Clicking a shelf reads it out in the tip along the bottom and opens a **Feed**
button inside it; clicking the shelf again closes it. Feeding is never the
click on the row itself, so nothing is eaten by a second click somebody meant
as a second look. A shelf the machine cannot spare, or one this
window has no room for, is dimmed rather than hidden: the refusal is
information. A meal drops you back on the list of windows with what happened;
a refusal leaves you where you are, because the next shelf along may well
work.

**All food**, reached from the button at the top, for when the question is
"what has this machine got spare" rather than "what do I feed this". The same
shelves, with nothing to spend them on, and clicking one still reads it out.

**The tip** is pinned along the bottom of the two food views and is never
empty there. It is the one line that answers "what is this thing", and a line
you have to scroll to find cannot do that - so the shelves themselves carry
only their numbers and the description lives here. The list of windows has no
tip at all: every row already says what it is.

Escape steps back out of a view before it closes the panel, so one key is the
way out of wherever you are.

The panel **draws and asks; it decides nothing**. Everything it shows comes
from `battles-ctl roster --json`, and feeding goes back through
`battles-ctl feed <address> <shelf>`, which is the same path the daemon takes.
Both work with the daemon stopped, because both are the files rather than the
process; what a stopped daemon costs you is the evolution animation, not the
evolution.

It cannot touch a window. Reading the window list and writing a record is the
whole of its reach - there is deliberately no button that would move, close or
focus anything, and a test greps `Roster.qml` to keep it that way.

While the panel is shut it still reads the roster once a minute, for the dot
and nothing else. While it is open it reads every five seconds, because a
window can close while you are looking at the list.

## From the command line

```bash
battles-ctl roster                  # every open window as a creature
battles-ctl roster --json           # the same, as the panel reads it
battles-ctl feed <address> staple   # one portion of FREE RAM
```

`roster` prints one line per window: name, type, level, stage, hunger out of
appetite, the win-loss record, and the address to feed it with.

## What the tests hold still

- A record is keyed by class, and survives the window closing.
- An appetite belongs to one running window, is keyed by pid *and* process
  start time so a recycled pid cannot inherit it, and is forgotten when the
  window is gone.
- A refusal - full creature, bare shelf, unknown window, a move it has not
  learned - costs nothing: no portion leaves the pantry, no appetite is spent
  and the carried moves do not move.
- A creature always knows the four moves it is carrying, whatever its record
  says, and always carries at least two of its own type.
- Experience only ever goes up, the ladder only ever gets slower, and it stops
  at the cap.
- Every evolved name still fits the 12-character name plate.
- A stage-1 creature cannot reach its type's strongest move; a stage-3 one
  knows all three.
- Nothing in `lib/creatures.py` or `Roster.qml` can reach a window.
