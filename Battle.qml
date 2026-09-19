// The battle screen.
//
// This draws; it does not decide. Every rule - who hits whom, for how much,
// whose turn it is, when it ends - lives in the daemon
// (lib/hyprscroll2d_battle.py), which publishes a snapshot to
// $XDG_RUNTIME_DIR/hyprscroll2d-battle.json after every change. This file
// watches that file and renders whatever it says. The split is deliberate:
// the rules are then testable without a screen, and a mistake in here cannot
// reach a window.
//
// The two fighters are the actual windows, not pictures of them - see
// BattleFighter.qml. Nothing is moved, floated, resized or re-parented to
// make that happen, which is why a battle cannot cost you a window: the only
// thing it can ever change is which grid cell the challenger ends up on, and
// the daemon does that afterwards with an ordinary layout message.
//
// The arena background is the desktop wallpaper, dimmed - the real one, so
// the fight happens somewhere that looks like this machine.
//
// IPC target: `hyprscroll2d-battle`. The other two targets in this pair of
// plugins, `hyprscroll2d` and `hyprscroll2d-gamepad`, are taken, and a target
// has to be unique across the whole shell process.

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons

Item {
    id: root

    property var state: ({})

    readonly property string statePath: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/hyprscroll2d-battle.json"
    readonly property string wallpaper: Quickshell.env("HOME") + "/.local/state/omarchy/current/background"
    readonly property string controlCommand: decodeURIComponent(
        Qt.resolvedUrl("bin/battles-ctl").toString().replace(/^file:\/\//, ""))

    readonly property bool active: state.active === true
    // Two things can be on this screen, and only ever one at a time: a
    // battle, and a creature evolving. An evolution has no turns, no menus
    // and nothing to play - it is three beats of animation over the window
    // that earned it - so it borrows the arena, the name plate and the text
    // box and leaves the rest of the scene out.
    readonly property bool evolving: String(state.scene || "") === "evolve"
    readonly property var player: state.player || ({})
    readonly property var foe: state.foe || ({})
    readonly property string monitor: String(state.monitor || "")
    readonly property string effect: String(state.effect || "")
    readonly property string message: String(state.message || "")
    // The daemon says which of the two was last used to play. The controls
    // are named for that one: showing both sets at once asks the player to
    // read past four labels that are not theirs to find the two that are.
    readonly property bool padInput: String(state.input || "keys") === "pad"
    readonly property bool menuOpen: state.menu === true
    readonly property bool actionOpen: state.action === true
    readonly property bool itemOpen: state.item === true
    // A menu is up, so the battle is waiting on you.
    readonly property bool choosing: menuOpen || actionOpen || itemOpen
    readonly property var shelves: state.shelves || []
    readonly property int cursor: Number(state.cursor || 0)
    readonly property var moves: state.moves || []
    readonly property var actions: state.actions || []
    // Rises on every change the daemon publishes; the hit animations key off
    // it so two identical hits in a row still both play.
    readonly property int seq: Number(state.seq || 0)

    // A type reads faster as a colour than as a word. Deliberate accents: a
    // type is the creature's identity and has to mean the same thing on every
    // theme, so these do not follow one. All are mid tones, chosen to take
    // dark label text and to sit on a light or a dark background.
    readonly property var typeColors: ({
        "SHELL": "#5fb37a", "CODE": "#5f97d8", "NET": "#9a86e0",
        "CHAT": "#d8a04a", "MEDIA": "#d86e9a", "GAME": "#dc6a6a",
        "GLASS": "#6fb8bb"
    })

    // What the text box says while the pantry is open: the highlighted
    // shelf's own description and how much of it the machine has spare.
    readonly property string shelfNote: {
        var shelf = shelves[cursor]
        if (!shelf) return message
        var amount = shelf.unit === "MiB"
            ? (shelf.available >= 1024
               ? (shelf.available / 1024).toFixed(1) + " GIB"
               : Math.floor(shelf.available) + " MIB")
            : Math.floor(shelf.available) + (shelf.unit ? " " + shelf.unit : "")
        // One newline, not two: a long note plus a blank line plus the
        // reading is five lines, and five lines do not fit the box.
        return String(shelf.note || "") + "\n" + amount + " SPARE"
    }

    function typeColor(name) {
        var value = typeColors[String(name || "")]
        return value !== undefined ? value : "#6fb8bb"
    }

    function load(text) {
        var parsed
        try {
            parsed = JSON.parse(text)
        } catch (e) {
            return  // caught mid-write; the next change brings a whole file
        }
        root.state = parsed || ({})
    }

    function send(argument) {
        Quickshell.execDetached([root.controlCommand, argument])
    }

    function send2(argument, value) {
        Quickshell.execDetached([root.controlCommand, argument, value])
    }

    // Keyboard to battle control. Returns "" for anything the battle does not
    // use, so those keys are left alone rather than swallowed.
    function keyAction(key, text) {
        switch (key) {
        case Qt.Key_Left:       return "left"
        case Qt.Key_Right:      return "right"
        case Qt.Key_Up:         return "up"
        case Qt.Key_Down:       return "down"
        case Qt.Key_Return:
        case Qt.Key_Enter:
        case Qt.Key_Space:      return "confirm"
        case Qt.Key_Backspace:  return "back"
        }
        switch (String(text || "").toLowerCase()) {
        case "h": return "left"
        case "l": return "right"
        case "k": return "up"
        case "j": return "down"
        // Where every handheld emulator puts A and B, and the pair this
        // names in the hints - one hand on the arrows, one on these.
        case "z": return "confirm"
        case "x": return "back"
        }
        return ""
    }

    // The live window behind a fighter, by Hyprland address. Quickshell and
    // hyprctl disagree about the "0x" prefix, so neither side is trusted.
    // `tick` is in the signature only so the bindings below re-run while the
    // toplevel list is still filling in.
    function toplevelFor(address, tick) {
        var wanted = String(address || "").toLowerCase().replace(/^0x/, "")
        if (wanted === "") return null
        var list = []
        try {
            list = Hyprland.toplevels ? Hyprland.toplevels.values : []
        } catch (e) {
            return null
        }
        for (var i = 0; i < list.length; i++) {
            var found = String(list[i].address || "").toLowerCase().replace(/^0x/, "")
            if (found === wanted) return list[i].wayland
        }
        return null
    }

    property int toplevelTick: 0
    readonly property var playerToplevel: toplevelFor(player.address, toplevelTick)
    readonly property var foeToplevel: toplevelFor(foe.address, toplevelTick)

    Timer {
        // Only while a battle is up, and only until both have been found.
        interval: 400
        repeat: true
        running: root.active && (!root.playerToplevel || !root.foeToplevel)
        onTriggered: root.toplevelTick++
    }

    FileView {
        id: file
        path: root.statePath
        watchChanges: true
        // text() is stale inside the change signal, so re-read first.
        onFileChanged: reload()
        onLoaded: root.load(text())
        onLoadFailed: root.state = ({})
    }

    // The daemon writes the file when it starts and removes it when it stops,
    // and a watch on a path that does not exist yet never fires.
    Timer {
        interval: 3000
        running: true
        repeat: true
        onTriggered: file.reload()
    }

    // Last line of defence. The daemon has its own timeouts, but if it stops
    // publishing while a battle is up - killed, wedged, whatever - nothing
    // else would take this screen down, and it is holding the keyboard. Two
    // minutes of an unchanging battle and the overlay lets go by itself.
    property int watchdogSeq: -1

    Timer {
        interval: 120000
        running: root.active
        repeat: true
        onTriggered: {
            if (root.watchdogSeq === root.seq) {
                root.state = ({})
                root.send("stop")
            }
            root.watchdogSeq = root.seq
        }
    }

    onActiveChanged: if (active) watchdogSeq = -1

    IpcHandler {
        target: "hyprscroll2d-battle"

        // Force a battle between the focused window and its neighbour, for
        // working on this screen without waiting for a 25% roll to land.
        function debugBattle(): string {
            root.send("debug")
            return "requested"
        }

        function cancel(): string {
            root.send("cancel")
            return "cancelled"
        }

        function shown(): string {
            return root.active ? "true" : "false"
        }
    }

    Variants {
        model: Quickshell.screens

        PanelWindow {
            id: panel

            required property var modelData
            screen: modelData

            // One screen only: the one the challenger is on. With no monitor
            // named, fall back to the focused one rather than every screen.
            readonly property var focusedMonitor: Hyprland.focusedMonitor
            readonly property bool mine: root.monitor !== ""
                ? root.monitor === String(modelData.name)
                : (!focusedMonitor || String(focusedMonitor.name) === String(modelData.name))

            visible: root.active && mine
            anchors { top: true; bottom: true; left: true; right: true }
            color: "transparent"
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.namespace: "hyprscroll2d-battle"
            WlrLayershell.layer: WlrLayer.Overlay
            // The battle holds the keyboard, which is what makes the windows
            // behind it inert while they fight. Escape always gets out, and
            // the focus is dropped the moment the battle is over.
            WlrLayershell.keyboardFocus: root.active
                ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

            // One font pixel. Everything in the scene is sized off it, so the
            // screen scales with the monitor rather than with fontconfig.
            readonly property int unit: Math.max(2, Math.round(height / 300))
            readonly property int frame: Math.max(2, Math.round(unit * 0.7))

            onVisibleChanged: {
                if (!visible) return
                foeFighter.enter()
                playerFighter.enter()
            }

            FocusScope {
                id: keys

                anchors.fill: parent
                focus: true

                // The keyboard plays the battle too. A collision a keyboard
                // binding caused is a battle like any other, and reaching for
                // a controller to finish one you started with SUPER+SHIFT+H
                // would be a silly thing to have to do. Arrows and hjkl move
                // the cursor, Enter and Space take the option, Backspace
                // steps back, Escape leaves.
                Keys.onEscapePressed: root.send("cancel")
                Keys.onPressed: function (event) {
                    var name = root.keyAction(event.key, event.text)
                    if (name === "") return
                    root.send2("key", name)
                    event.accepted = true
                }

                // ----------------------------------------------------- arena

                Image {
                    anchors.fill: parent
                    source: Qt.resolvedUrl("file://" + root.wallpaper)
                    fillMode: Image.PreserveAspectCrop
                    cache: false
                    asynchronous: true
                }

                // Dim it enough that pixel text reads over any wallpaper, and
                // darken the bottom where the text box sits.
                Rectangle {
                    anchors.fill: parent
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: Util.alpha(Color.background, 0.60) }
                        GradientStop { position: 0.55; color: Util.alpha(Color.background, 0.70) }
                        GradientStop { position: 1.0; color: Util.alpha(Color.background, 0.93) }
                    }
                }

                // A faint diagonal sweep across the arena, the way a battle
                // backdrop has one. Kept low contrast: it is a backdrop.
                Repeater {
                    model: 7

                    Rectangle {
                        required property int index
                        width: keys.width * 2
                        height: keys.height * 0.045
                        x: -keys.width * 0.5
                        y: index * keys.height * 0.105 - keys.height * 0.08
                        rotation: -12
                        transformOrigin: Item.Center
                        color: Util.alpha(Color.accent, 0.055)
                    }
                }

                // -------------------------------------------------- fighters

                BattleFighter {
                    id: foeFighter

                    creature: root.foe
                    toplevel: root.foeToplevel
                    tint: root.typeColor(root.foe.type)
                    unit: panel.unit
                    frameWidth: panel.frame
                    struck: root.effect === "hit-foe"
                    fainted: root.effect === "faint-foe" || Number(root.foe.hp || 1) <= 0
                    pulse: root.seq
                    entryFrom: keys.width * 0.5
                    visible: root.active && !root.evolving

                    x: keys.width * 0.60
                    y: keys.height * 0.09
                    width: keys.width * 0.26
                    height: keys.height * 0.25
                }

                BattleFighter {
                    id: playerFighter

                    creature: root.player
                    toplevel: root.playerToplevel
                    tint: root.typeColor(root.player.type)
                    unit: panel.unit
                    frameWidth: panel.frame
                    struck: root.effect === "hit-player"
                    fainted: root.effect === "faint-player" || Number(root.player.hp || 1) <= 0
                    pulse: root.seq
                    entryFrom: -keys.width * 0.5
                    visible: root.active

                    x: root.evolving ? keys.width * 0.34 : keys.width * 0.10
                    y: root.evolving ? keys.height * 0.11 : keys.height * 0.34
                    width: keys.width * 0.32
                    height: root.evolving ? keys.height * 0.34 : keys.height * 0.30

                    // It walks to the middle of the arena rather than cutting
                    // there: the animation is the whole content of this
                    // scene, so every part of it is worth moving.
                    Behavior on x { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
                    Behavior on y { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
                    Behavior on height { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
                }

                // The evolution itself: a white flash over the whole arena
                // that quickens as it goes, which is what the shows this is
                // imitating do with the same three seconds. It sits over the
                // fighters and under the text box, so the window behind is
                // still visible through every dip.
                Rectangle {
                    id: shimmer

                    anchors.fill: parent
                    color: Color.foreground
                    opacity: 0
                    visible: root.evolving && opacity > 0

                    readonly property bool shifting: root.effect === "evolve-shift"

                    SequentialAnimation {
                        running: shimmer.shifting
                        loops: Animation.Infinite

                        NumberAnimation { target: shimmer; property: "opacity"; to: 0.85; duration: 260 }
                        NumberAnimation { target: shimmer; property: "opacity"; to: 0.10; duration: 220 }
                        NumberAnimation { target: shimmer; property: "opacity"; to: 0.90; duration: 170 }
                        NumberAnimation { target: shimmer; property: "opacity"; to: 0.10; duration: 140 }
                        NumberAnimation { target: shimmer; property: "opacity"; to: 0.95; duration: 110 }
                        NumberAnimation { target: shimmer; property: "opacity"; to: 0.15; duration: 90 }
                    }

                    // The flash on arrival: one long fade out of white, so the
                    // evolved name is read through it rather than after it.
                    NumberAnimation {
                        target: shimmer
                        property: "opacity"
                        from: 1.0
                        to: 0.0
                        duration: 900
                        running: root.evolving && root.effect === "evolve-done"
                    }

                    onShiftingChanged: if (!shifting && root.effect !== "evolve-done") opacity = 0
                }

                // -------------------------------------------------- HP boxes

                BattleStatusBox {
                    creature: root.foe
                    tint: root.typeColor(root.foe.type)
                    unit: panel.unit
                    frameWidth: panel.frame
                    showNumbers: false
                    visible: root.active && !root.evolving
                             && String(root.foe.name || "") !== ""

                    x: keys.width * 0.06
                    y: keys.height * 0.10
                    width: keys.width * 0.29
                }

                BattleStatusBox {
                    creature: root.player
                    tint: root.typeColor(root.player.type)
                    unit: panel.unit
                    frameWidth: panel.frame
                    showNumbers: !root.evolving
                    visible: root.active && String(root.player.name || "") !== ""

                    x: root.evolving ? keys.width * 0.335 : keys.width * 0.58
                    y: root.evolving ? keys.height * 0.50 : keys.height * 0.46
                    width: root.evolving ? keys.width * 0.33 : keys.width * 0.33
                }

                // -------------------------------------------------- text box

                Rectangle {
                    id: textBox

                    x: keys.width * 0.03
                    width: keys.width * 0.94
                    y: keys.height * 0.735
                    height: keys.height * 0.205
                    color: Util.alpha(Color.background, 0.95)
                    border.width: panel.frame * 2
                    border.color: Util.alpha(Color.foreground, 0.88)

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: panel.frame * 3
                        color: "transparent"
                        border.width: Math.max(1, Math.round(panel.frame / 2))
                        border.color: Util.alpha(Color.foreground, 0.24)
                    }

                    PixelText {
                        id: line

                        x: panel.unit * 10
                        // Centred in the box rather than pinned to the top, so
                        // a one-line message does not sit in a void.
                        y: (textBox.height - implicitHeight) / 2
                        width: root.itemOpen ? textBox.width * 0.42 - panel.unit * 14
                             : root.choosing ? textBox.width * 0.50 - panel.unit * 14
                             : textBox.width - panel.unit * 20
                        // The narration is the thing you are reading, so it
                        // gets a size of its own rather than the base unit.
                        pixel: root.choosing ? panel.unit : panel.unit + 1
                        // The pantry note runs to three lines plus its
                        // reading; a tighter leading is what keeps that
                        // inside the box.
                        lineGap: root.itemOpen ? 2 : 4
                        color: Color.foreground
                        columns: Math.max(8, Math.floor(width / (6 * panel.unit)))
                        // Typewriter: the line arrives a letter at a time, the
                        // way it does on the machines this is imitating.
                        text: root.itemOpen ? root.shelfNote
                                            : root.message.substring(0, typed)

                        property int typed: 0
                    }

                    Timer {
                        interval: 16
                        running: root.active && line.typed < root.message.length
                        repeat: true
                        onTriggered: line.typed = Math.min(root.message.length, line.typed + 1)
                    }

                    Connections {
                        target: root
                        function onMessageChanged() { line.typed = 0 }
                    }

                    // The blinking "there is more" marker, once the line is in.
                    PixelText {
                        id: more

                        // Nothing to advance during an evolution: it runs
                        // itself, and the only key that does anything is the
                        // one that skips it.
                        visible: root.active && !root.choosing && !root.evolving
                                 && root.message !== ""
                            && line.typed >= root.message.length
                        text: ">"
                        pixel: panel.unit
                        color: Color.accent
                        x: textBox.width - panel.unit * 14
                        y: textBox.height - panel.unit * 16

                        SequentialAnimation on opacity {
                            loops: Animation.Infinite
                            running: more.visible
                            NumberAnimation { to: 0.12; duration: 460 }
                            NumberAnimation { to: 1.0; duration: 460 }
                        }
                    }

                    // ------------------------------------------------ moves

                    // FIGHT or RUN, in front of the move list. Running is
                    // free before the first blow and a gamble after it; START
                    // and Escape leave regardless, and always work.
                    Item {
                        id: actionMenu

                        visible: root.actionOpen
                        x: textBox.width * 0.50
                        y: panel.frame * 3 + panel.unit * 2
                        width: textBox.width * 0.50 - panel.frame * 3 - panel.unit * 2
                        height: textBox.height - panel.frame * 6 - panel.unit * 4

                        Rectangle {
                            anchors.fill: parent
                            color: Util.alpha(Color.foreground, 0.05)
                            border.width: Math.max(1, Math.round(panel.frame / 2))
                            border.color: Util.alpha(Color.foreground, 0.32)
                        }

                        // A 2x2 grid, the same shape as the move list, so the
                        // same hand movement means the same thing in both.
                        // Three options leave a hole; the cursor refuses it.
                        Grid {
                            anchors.fill: parent
                            anchors.margins: panel.unit * 4
                            columns: 2
                            spacing: panel.unit * 3

                            Repeater {
                                model: root.actions

                                Item {
                                    id: choice

                                    required property var modelData
                                    required property int index
                                    readonly property bool picked: index === root.cursor

                                    width: (actionMenu.width - panel.unit * 11) / 2
                                    height: (actionMenu.height - panel.unit * 11) / 2

                                    Rectangle {
                                        anchors.fill: parent
                                        color: choice.picked ? Util.alpha(Color.accent, 0.16) : "transparent"
                                        border.width: choice.picked ? Math.max(1, Math.round(panel.frame / 2)) : 0
                                        border.color: Color.accent
                                    }

                                    Canvas {
                                        visible: choice.picked
                                        width: panel.unit * 3
                                        height: panel.unit * 5
                                        x: panel.unit * 2
                                        anchors.verticalCenter: parent.verticalCenter
                                        onVisibleChanged: requestPaint()
                                        onPaint: {
                                            var context = getContext("2d")
                                            context.reset()
                                            context.fillStyle = Color.accent
                                            context.beginPath()
                                            context.moveTo(0, 0)
                                            context.lineTo(width, height / 2)
                                            context.lineTo(0, height)
                                            context.closePath()
                                            context.fill()
                                        }
                                    }

                                    PixelText {
                                        id: label
                                        x: panel.unit * 7
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: String(choice.modelData)
                                        pixel: panel.unit
                                        color: choice.picked ? Color.accent : Color.foreground
                                    }
                                }
                            }
                        }
                    }

                    // The pantry. One column rather than a grid: every row
                    // carries a reading and a note, and those do not fit
                    // side by side.
                    Item {
                        id: pantry

                        visible: root.itemOpen
                        x: textBox.width * 0.42
                        y: panel.frame * 3 + panel.unit * 2
                        width: textBox.width * 0.58 - panel.frame * 3 - panel.unit * 2
                        height: textBox.height - panel.frame * 6 - panel.unit * 4

                        Rectangle {
                            anchors.fill: parent
                            color: Util.alpha(Color.foreground, 0.05)
                            border.width: Math.max(1, Math.round(panel.frame / 2))
                            border.color: Util.alpha(Color.foreground, 0.32)
                        }

                        Grid {
                            id: shelfList

                            anchors.fill: parent
                            anchors.margins: panel.unit * 3
                            columns: 2
                            spacing: panel.unit

                            readonly property int rows: Math.max(1,
                                Math.ceil(root.shelves.length / columns))
                            // The spacing between rows has to come out of the
                            // rows, or the last shelf falls off the bottom.
                            readonly property int rowHeight: Math.floor(
                                (height - spacing * (rows - 1)) / rows)
                            readonly property int columnWidth: Math.floor(
                                (width - spacing) / columns)

                            Repeater {
                                model: root.shelves

                                Item {
                                    id: shelf

                                    required property var modelData
                                    required property int index
                                    readonly property bool picked: index === root.cursor
                                    // An empty shelf is still listed - that is
                                    // half the joke - but it reads as empty.
                                    readonly property bool bare: Number(modelData.servings || 0) <= 0

                                    width: shelfList.columnWidth
                                    height: shelfList.rowHeight

                                    Rectangle {
                                        anchors.fill: parent
                                        color: shelf.picked ? Util.alpha(Color.accent, 0.16) : "transparent"
                                        border.width: shelf.picked ? Math.max(1, Math.round(panel.frame / 2)) : 0
                                        border.color: Color.accent
                                    }

                                    Canvas {
                                        visible: shelf.picked
                                        width: panel.unit * 3
                                        height: panel.unit * 4
                                        x: panel.unit
                                        anchors.verticalCenter: parent.verticalCenter
                                        onPaint: {
                                            var context = getContext("2d")
                                            context.reset()
                                            context.fillStyle = Color.accent
                                            context.beginPath()
                                            context.moveTo(0, 0)
                                            context.lineTo(width, height / 2)
                                            context.lineTo(0, height)
                                            context.closePath()
                                            context.fill()
                                        }
                                    }

                                    PixelText {
                                        id: shelfName
                                        x: panel.unit * 6
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: String(shelf.modelData.name || "")
                                        pixel: Math.max(2, panel.unit - 1)
                                        color: shelf.bare
                                            ? Util.alpha(Color.foreground, 0.38)
                                            : (shelf.picked ? Color.accent : Color.foreground)
                                    }

                                    PixelText {
                                        anchors.right: parent.right
                                        anchors.rightMargin: panel.unit * 2
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: shelf.bare ? "NONE"
                                                         : "x" + String(shelf.modelData.servings)
                                        pixel: Math.max(2, panel.unit - 1)
                                        color: shelf.bare
                                            ? Util.alpha(Color.foreground, 0.38)
                                            : Util.alpha(Color.foreground, 0.72)
                                    }
                                }
                            }
                        }
                    }

                    Item {
                        id: menu

                        visible: root.menuOpen
                        x: textBox.width * 0.50
                        y: panel.frame * 3 + panel.unit * 2
                        width: textBox.width * 0.50 - panel.frame * 3 - panel.unit * 2
                        height: textBox.height - panel.frame * 6 - panel.unit * 4

                        Rectangle {
                            anchors.fill: parent
                            color: Util.alpha(Color.foreground, 0.05)
                            border.width: Math.max(1, Math.round(panel.frame / 2))
                            border.color: Util.alpha(Color.foreground, 0.32)
                        }

                        Grid {
                            anchors.fill: parent
                            anchors.margins: panel.unit * 4
                            columns: 2
                            spacing: panel.unit * 3

                            Repeater {
                                model: root.moves

                                Item {
                                    id: slot

                                    required property var modelData
                                    required property int index
                                    readonly property bool picked: index === root.cursor

                                    width: (menu.width - panel.unit * 11) / 2
                                    height: (menu.height - panel.unit * 11) / 2

                                    Rectangle {
                                        anchors.fill: parent
                                        color: slot.picked ? Util.alpha(Color.accent, 0.16) : "transparent"
                                        border.width: slot.picked ? Math.max(1, Math.round(panel.frame / 2)) : 0
                                        border.color: Color.accent
                                    }

                                    // The selection cursor, a solid triangle.
                                    Canvas {
                                        visible: slot.picked
                                        width: panel.unit * 3
                                        height: panel.unit * 5
                                        x: panel.unit
                                        y: panel.unit * 2
                                        onPaint: {
                                            var context = getContext("2d")
                                            context.reset()
                                            context.fillStyle = Color.accent
                                            context.beginPath()
                                            context.moveTo(0, 0)
                                            context.lineTo(width, height / 2)
                                            context.lineTo(0, height)
                                            context.closePath()
                                            context.fill()
                                        }
                                    }

                                    PixelText {
                                        x: panel.unit * 6
                                        y: panel.unit * 2
                                        text: String(slot.modelData.name || "")
                                        pixel: Math.max(2, panel.unit - 1)
                                        color: slot.picked ? Color.accent : Color.foreground
                                    }

                                    Row {
                                        x: panel.unit * 6
                                        y: panel.unit * 11
                                        spacing: panel.unit * 3

                                        BattleTypeChip {
                                            typeName: String(slot.modelData.type || "")
                                            unit: Math.max(2, panel.unit - 1)
                                            tint: root.typeColor(slot.modelData.type)
                                        }

                                        PixelText {
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: "PWR " + String(slot.modelData.power || 0)
                                            pixel: Math.max(2, panel.unit - 2)
                                            color: Util.alpha(Color.foreground, 0.62)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // -------------------------------------------------- controls

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: keys.height * 0.975 - height
                    spacing: panel.unit * 7
                    opacity: 0.5

                    Repeater {
                        // There is nothing to play during an evolution, so
                        // the only control worth naming is the one that
                        // skips it - and it skips the picture, never the
                        // level, which was written down before this began.
                        model: root.evolving
                            ? (root.padInput
                                ? [ { key: "START", label: "SKIP" } ]
                                : [ { key: "ESC", label: "SKIP" } ])
                            : (root.padInput
                            ? [
                                { key: "D-PAD", label: "PICK" },
                                { key: "A", label: "OK" },
                                { key: "B", label: root.menuOpen ? "BACK" : "NEXT" },
                                { key: "START", label: "LEAVE" }
                            ]
                            : [
                                { key: "ARROWS", label: "PICK" },
                                { key: "Z", label: "OK" },
                                { key: "X", label: root.menuOpen ? "BACK" : "NEXT" },
                                { key: "ESC", label: "LEAVE" }
                            ])

                        Row {
                            id: hint

                            required property var modelData
                            spacing: panel.unit * 2

                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: hintKey.implicitWidth + panel.unit * 4
                                height: hintKey.implicitHeight + panel.unit * 4
                                color: Util.alpha(Color.foreground, 0.16)

                                PixelText {
                                    id: hintKey
                                    anchors.centerIn: parent
                                    text: hint.modelData.key
                                    pixel: Math.max(2, panel.unit - 2)
                                    color: Color.foreground
                                    shadowColor: "transparent"
                                }
                            }

                            PixelText {
                                anchors.verticalCenter: parent.verticalCenter
                                text: hint.modelData.label
                                pixel: Math.max(2, panel.unit - 2)
                                color: Util.alpha(Color.foreground, 0.85)
                            }
                        }
                    }
                }
            }
        }
    }
}
