# Food

Creatures get hungry, and a computer has plenty lying around.

Apps are creatures, so apps are not food. What is left is the stuff every
Linux desktop has going spare - free memory, page cache, swap, entropy, dead
processes, whatever is rotting in `/tmp` - and that turns out to be the better
joke anyway. **Open a browser and your creatures go hungry.** The pantry is a
live reading of the machine you are actually sitting at, so a fresh boot is a
banquet and a long compile is a famine.

## The rule everything else obeys

**Nothing is consumed. Nothing is changed. Nothing is even written except one
small ledger of our own.**

The pantry reads counters and sizes out of `/proc` and one `statvfs`. It does
not delete files, drop caches, free memory, reap zombies, signal a process or
ask for root, and it never reads the contents of anything - no browser
profiles, no documents, no file bodies, only numbers the kernel already
publishes about itself. The machine is in exactly the same state after a feast
as it was before it. A test greps `lib/pantry.py` and fails if a future shelf
ever reaches for a write, an unlink, a signal or a subprocess.

## The shelves

| Shelf | Reading | Portion | What it does |
| --- | --- | --- | --- |
| **FREE RAM** | `MemAvailable` | 512 MiB | The staple. Heals 30%. Plentiful on an idle machine, gone the moment something hogs it. |
| **PAGE CACHE** | `Cached` | 1 GiB | Leftovers. Heals 12%. Always plenty, never worth much. |
| **SWAP** | `SwapTotal - SwapFree` | 256 MiB | Junk food. Heals 48% - and drops speed by 30% for the rest of the battle. Swapping is slow; so is eating it. |
| **ENTROPY** | `entropy_avail` | 64 bits | Candy. Heals anywhere from nothing to double, decided per bite. Reading the pool does not drain it. |
| **ZOMBIES** | processes in state `Z` | 1 | Carrion. Heals 35% and raises attack. Rare, grim, bracing. |
| **IDLE CYCLES** | load average against core count | 10% | A vitamin. Heals 10% and raises speed - the one stat no other shelf hands out. Plentiful on a quiet machine, gone under a compile. |
| **TMP SCRAPS** | `/tmp` used bytes | 256 MiB | Barely a mouthful. Heals 9%. On a tmpfs it is memory too, which is a nice accident. |

Healing is a fraction of the creature's **own** maximum HP, so a 4K browser
and a little terminal both get a meal that means something to them.

Two of the seven have a character beyond the numbers. Swap is the one you take
when you are desperate, and regret. Entropy is the one you take when you are
feeling lucky - it multiplies its heal by 0, 0.5, 1, 1.5 or 2, so it is as
likely to do nothing as to do twice the job.

## The ledger, and why the fiction holds

Here is the obvious hole: if eating changes nothing, what stops you feeding
the same 512 MiB to a creature over and over?

A ledger. Every portion eaten is written down with the time it was taken, and
the pantry subtracts what is still outstanding from the live reading:

```
available = reading - (what is eaten and has not grown back)
```

A portion regenerates **linearly over four minutes**, so it comes back
gradually the way the resource itself would rather than snapping back all at
once. Eat half the free RAM and the shelf is visibly thinner for a while.

That keeps the fiction honest in both directions:

- **You cannot eat what the machine does not have.** Open something enormous
  and the staple shelf empties on its own, with no help from the ledger.
- **You cannot eat the same thing twice.** The ledger is the only reason a
  portion is unavailable, and it is unavailable *to the game*, not to the
  machine.

The ledger lives in `~/.local/state/hyprscroll2d/pantry.json` and survives a
shell restart, because a pantry you could refill by restarting the shell would
not be much of a pantry. It uses wall-clock time for the same reason. A
corrupt or half-written one is ignored rather than fatal, and entries that
have fully grown back are pruned away.

## Eating

`ITEM` sits between `FIGHT` and `RUN` in the battle menu. It opens the pantry:
one row per shelf, each showing how many portions are there, with the
highlighted shelf's description and live reading in the text box beside it.

An empty shelf is still listed - that is half the joke - and picking it costs
nothing but a line of text.

**Eating costs the turn.** The other window gets a free swing while you are
chewing, which is what stops `ITEM` being strictly better than `FIGHT`.

## Growing

Every shelf is worth some nourishment:

```
FREE RAM 34   PAGE CACHE 12   SWAP 40   ENTROPY 18
ZOMBIES 30    IDLE CYCLES 14  SCRAPS 9
```

**In a battle**, 60 points of it is a level, there and then: 8 maximum HP and
2 to each of attack, defense and speed, and the sting that until now only
played when you won. So a long battle against something much bigger than you
is winnable if the machine has enough spare memory to eat your way up - which
is a sentence that makes no sense anywhere but here. That level is for the
fight only; nothing is carried out of it.

**At the desk**, the same nourishment is worth twice as much experience, and
experience is kept. That is the other way to feed something, and it is a
different bargain: in a fight you eat to survive the next swing, and between
fights you eat to become something. See [CREATURES.md](CREATURES.md).

## Checking the fridge

```bash
bin/hyprbattles-ctl pantry
```

```
FREE RAM     14.6 GiB     29 servings   Plain, filling, and gone the moment a browser opens.
PAGE CACHE   12.8 GiB     12 servings   Yesterday's reads, still warm. Cheap and not very filling.
SWAP         2.1 GiB       8 servings   Enormously filling. Sits heavy, and slows you right down.
ENTROPY      256 bits      4 servings   Pure randomness. Nobody knows what it does until it is eaten.
ZOMBIES      6             6 servings   Processes nobody reaped. Grim, rare, and very good for you.
TMP SCRAPS   1.2 GiB       4 servings   Whatever the last hour left in /tmp. Barely a mouthful.
```

That is a read-only reading, ledger included, and it works with or without a
battle running.

## Feeding outside a battle

Built, in the bar panel: pick a window, pick a food. It was held back for a
long time for a good reason - a creature used to be derived from its window at
the moment a battle started and not exist in between, so there was no HP
sitting anywhere to heal and nowhere to keep what a meal had done.

What unlocked it was giving creatures a record of their own, keyed by window
class so it can outlive the window, and an appetite bought with uptime so a
panel with a feed button is not a level button. Both are in
[CREATURES.md](CREATURES.md); the short version is that feeding is gated
twice, and the pantry is only the first gate:

- the machine has to have the food spare - this document, and the ledger;
- the creature has to have room for it - the age of its eldest open window,
  shared by every window of its class.

A meal outside a battle heals nothing. There is nothing to heal: HP only
exists while a fight is on. It buys experience, and enough of that evolves the
creature.

```bash
bin/hyprbattles-ctl roster                  # every window, with how hungry it is
bin/hyprbattles-ctl feed <address> staple   # one portion of FREE RAM
```

## Adding a shelf

One entry in `SHELVES` in [`lib/pantry.py`](../lib/pantry.py): a name, a note,
a portion size, what eating it does, and a `reading` that takes the roots dict
and returns a number. Anything that is a counter or a size the kernel already
publishes is fair game - inode counts, load average, uptime, open file
descriptors. Anything that requires reading somebody's data, or changing
something, is not.
