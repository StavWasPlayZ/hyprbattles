"""Moving a window one cell, whatever layout is underneath it.

Two families of layout can swap two windows, and they are asked in two
different ways:

  * a scrolling layout - Demon Slayer's Hyprscroll2D, and anything else that
    grids a workspace - takes its own layout message, `layoutmsg move left`;
  * dwindle, master and every other stock layout take the compositor's own
    `movewindow` dispatcher, which swaps with the neighbour in a direction.

Both end up doing the same thing to the desktop, so battles do not care which
one ran - only that two windows changed places. This module is the one place
that knows the difference: which command to send, which one to fall back to,
and how to tell a swap from a step into an empty cell. It is pure: no sockets,
no subprocesses, no compositor. `bin/battles` and `bin/battles-ctl` both go
through it, so there is one answer to "how is a window moved" rather than two
that can drift apart.

The commands are Lua expressions, because this Hyprland is configured in Lua
and evaluates `hl.dispatch(<what was sent>)`; a classic dispatcher string is a
syntax error that fails silently. A test pins that down.
"""

# The focused window, one cell, in a direction. `%s` is the direction in the
# spelling that family uses - a word for the layout message, a letter for the
# dispatcher.
STYLES = {
    "layout": 'hl.dsp.layout("move %s")',
    "window": 'hl.dsp.window.move({ direction = "%s" })',
}

DIRECTIONS = {"left": "l", "right": "r", "up": "u", "down": "d"}
OPPOSITES = {"left": "right", "right": "left", "up": "down", "down": "up"}

# Layouts whose own move message is the one that swaps windows, as
# `getoption general:layout` names them once any `lua:` prefix is off.
# Anything not listed here is moved with the dispatcher, which is what dwindle
# and master want.
SCROLLING = ("hyprscroll2d", "scroller", "scrolling", "hyprscrolling")


def layout_name(option):
    """The layout out of a `getoption general:layout` reply.

    Hyprland reports a Lua layout as `lua:hyprscroll2d`; the prefix says where
    the layout came from, not which layout it is.
    """
    name = str((option or {}).get("str") or "").strip().lower()
    return name.split(":")[-1]


def style_for(layout):
    """Which family a layout belongs to."""
    return "layout" if layout in SCROLLING else "window"


def order(layout):
    """Both styles, the likelier one first.

    Trying the other one after the first changed nothing is what makes this
    work on a setup where the layout differs per workspace: a layout message
    a layout does not understand is a no-op, and a no-op is visible - nothing
    on screen moved.
    """
    first = style_for(layout)
    return (first, "window" if first == "layout" else "layout")


def command(style, direction):
    """The Lua expression that moves the focused window, or "" for nonsense."""
    template = STYLES.get(style)
    if template is None or direction not in DIRECTIONS:
        return ""
    return template % (direction if style == "layout"
                       else DIRECTIONS[direction])


def placement(clients):
    """Where every tiled window is, as {address: (x, y, width, height, ws)}.

    Floating windows are left out: they do not take part in a layout's idea of
    a cell, so they cannot be collided with.

    This is only ever compared against another reading of the same kind, to
    answer "did that command do anything at all". It is no use for answering
    "did two windows swap" - see swapped().
    """
    places = {}
    for client in clients or []:
        address = str(client.get("address") or "").lower()
        if not address or not client.get("mapped") or client.get("floating"):
            continue
        position = list(client.get("at") or (0, 0))
        size = list(client.get("size") or (0, 0))
        if len(position) < 2 or len(size) < 2:
            continue
        workspace = (client.get("workspace") or {}).get("id")
        places[address] = (position[0], position[1], size[0], size[1],
                           workspace)
    return places


def _overlaps(start, length, other_start, other_length):
    """Whether two spans share any of the axis at all - whether two windows
    are in the same row, or in the same column."""
    return (min(start + length, other_start + other_length)
            - max(start, other_start)) > 0


def neighbour(address, places, direction):
    """The nearest window in that direction, within one reading.

    Everything here is relative, and deliberately so. A scrolling layout moves
    the camera along with the window, so after a swap the window that moved
    can be sitting at the very same pixel it started at while every other
    window on the workspace has shifted - absolute coordinates compared across
    two readings would call that no move at all, or call an unrelated pan a
    swap. Who is next to whom survives a pan, because a pan moves everybody by
    the same amount.
    """
    me = places.get(address)
    if not me or direction not in DIRECTIONS:
        return ""
    x, y, width, height, workspace = me
    closest, shortest = "", None
    for other, (ox, oy, owidth, oheight, oworkspace) in places.items():
        if other == address or oworkspace != workspace:
            continue
        if direction in ("left", "right"):
            if not _overlaps(y, height, oy, oheight):
                continue        # not in this row
            gap = x - (ox + owidth) if direction == "left" else ox - (x + width)
        else:
            if not _overlaps(x, width, ox, owidth):
                continue        # not in this column
            gap = y - (oy + oheight) if direction == "up" else oy - (y + height)
        if gap < -1:
            continue            # behind us, not in front
        if shortest is None or gap < shortest:
            closest, shortest = other, gap
    return closest


def swapped(address, direction, before, after):
    """The window this one changed places with, or "" if it displaced nobody.

    A swap is the pair changing sides: whoever was in the way is on the other
    side of this window afterwards. A move into an empty cell has nobody in
    the way to begin with, and a move that crossed a gap to land short of a
    far window leaves that window on the same side it was on - neither is a
    collision.
    """
    partner = neighbour(address, before, direction)
    if not partner:
        return ""
    back = OPPOSITES.get(direction, "")
    return partner if neighbour(address, after, back) == partner else ""
