// The bar panel: every open window as a creature, and the food to feed it.
//
// This is the desk side of the game. A battle is something that happens to
// you; this is where you go when you want to make a window stronger on
// purpose. One card per creature - what it fights as, what level it has
// reached, what it has won, how much more it can eat today - and a feed
// button on each card that opens the pantry for that one creature.
//
// A creature is a class and not a window, so a class with three windows open
// is one card wearing a x3, with one level, one record and one appetite
// between them. Listing it three times was three copies of one creature -
// and, worse, three appetites where the creature has only ever had one.
//
// Three views behind one icon, because each is a whole screen's worth on a
// panel this narrow: the roster, the food picker for one creature, and the
// pantry on its own for when the question is "what has this machine got
// spare" rather than "what do I feed this".
//
// It draws and asks; it decides nothing. Everything on screen comes out of
// `hyprbattles-ctl roster --json`, and feeding goes back through
// `hyprbattles-ctl feed <address> <shelf>`, which is the same path the daemon
// takes. Both work with the daemon stopped, so this panel keeps answering
// while the shell is restarting.
//
// Nothing here can touch a window. The panel can read the window list and
// write a creature's record, and that is the whole of its reach - it cannot
// move, close, focus or resize anything, and there is deliberately no button
// that would.

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
    id: root

    moduleName: "dev.cstav.omarchy.plugin.hyprbattles"
    ipcTarget: "hyprbattles-roster"
    manageIpc: false

    readonly property string controlCommand: decodeURIComponent(
        Qt.resolvedUrl("bin/hyprbattles-ctl").toString().replace(/^file:\/\//, ""))

    readonly property color foreground: bar ? bar.foreground : Color.foreground
    readonly property color dim: Qt.darker(foreground, 1.55)
    readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

    // The same eight accents the battle screen uses. A type has to mean the
    // same colour in the panel as it does in the arena, so these are copied
    // deliberately rather than taken from the theme - see Battle.qml.
    readonly property var typeColors: ({
        "SHELL": "#5fb37a", "AGENT": "#9cbf52", "CODE": "#5f97d8",
        "NET": "#9a86e0", "CHAT": "#d8a04a", "MEDIA": "#d86e9a",
        "GAME": "#dc6a6a", "GLASS": "#6fb8bb"
    })


    // The agents wear Omarchy's own faces. Two of them ship a coloured mark
    // with the shell's agents panel; the rest have a glyph in the menu row
    // that asks you to pick a default agent, some from the icon font and
    // some from Omarchy's own. An icon that disagrees with the desktop is a
    // second icon to learn, so none of these are drawn here - they are the
    // ones already on screen elsewhere, looked up by the same name.
    readonly property string agentAssets:
        "/usr/share/omarchy/shell/plugins/agents/assets/"
    readonly property var agentGlyphs: ({
        "aider": "󰚩", "claude": "󰛄", "codex": "", "copilot": "",
        "crush": "󰋑", "cursor-agent": "", "gemini": "󰫢",
        "goose": "󰚩", "grok": "", "hermes": "", "muse": "󰛤",
        "omp": "", "openclaw": "", "opencode": "", "pi": "",
        "qwen-code": "󰚩"
    })
    // Which of those glyphs are Omarchy's own font rather than the bar's.
    readonly property var agentGlyphFonts: ({
        "codex": "omarchy", "cursor-agent": "omarchy",
        "grok": "omarchy", "hermes": "omarchy", "omp": "omarchy",
        "openclaw": "omarchy", "opencode": "omarchy",
        "pi": "omarchy"
    })
    // What an agent nobody has drawn yet looks like: the menu's own word for
    // the whole row.
    readonly property string agentGlyph: "󰚩"

    // Ported from the shell's agents panel, which uses it for the same
    // choice: a mark drawn in white ships a `-light` twin for light
    // surfaces, and one that works on both (Claude's orange) ships one file.
    function channelLuminance(value) {
        var channel = Number(value)
        if (!isFinite(channel)) return 0
        return channel <= 0.03928 ? channel / 12.92
                                  : Math.pow((channel + 0.055) / 1.055, 2.4)
    }

    function isLightSurface(colour) {
        return 0.2126 * channelLuminance(colour.r)
             + 0.7152 * channelLuminance(colour.g)
             + 0.0722 * channelLuminance(colour.b) >= 0.5
    }

    // Every picture worth trying for one creature, best first. An agent is
    // asked for its Omarchy mark before anything else, then falls through to
    // the ordinary desktop lookup - which is what finds the agent apps that
    // do have a window class of their own.
    function markSources(row) {
        var sources = []
        var key = String((row && row.key) || "")
        if (row && String(row.type) === "AGENT" && key !== "") {
            if (isLightSurface(Color.background))
                sources.push("file://" + agentAssets + key + "-light.svg")
            sources.push("file://" + agentAssets + key + ".svg")
        }
        var icon = appIcon(key)
        if (icon !== "") sources.push(icon)
        return sources
    }

    // The letter to fall back on when no picture loaded. Only agents have
    // one: every other window either has a desktop icon or shows its type
    // chip and nothing else, the way it always did.
    function markGlyph(row) {
        if (!row || String(row.type) !== "AGENT") return ""
        var glyph = agentGlyphs[String(row.key || "")]
        return glyph !== undefined ? glyph : agentGlyph
    }

    function markGlyphFont(row) {
        var font = row ? agentGlyphFonts[String(row.key || "")] : undefined
        return font !== undefined ? font : fontFamily
    }

    // The page's own margin. The panel keeps none of its own (`padding: 0`)
    // so that scrolled content runs to the edge; this is what puts the air
    // back around it at rest.
    readonly property int pagePad: Style.spacing.popupPadding
    // The sides carry the scrollbar's half-gutter as well, so the top matches
    // them rather than matching the panel.
    readonly property int pageTop: pagePad + Style.space(16) / 2

    property var rows: []
    // Creatures whose windows are shut. They keep their levels, their record
    // and their moves; what they do not keep is an appetite, because an
    // appetite is bought with uptime and they have none.
    property var sleepingRows: []
    property var shelves: []
    property bool battlesOn: true
    property string selected: ""
    property string note: ""
    property bool loading: false

    // "roster" - the windows. "window" - one of them, in full.
    // "feed" - the pantry, for one of them.
    // "pantry" - the same shelves with nothing to spend them on, which is the
    // read-only answer to "what is going spare".
    property string view: "roster"
    property string feeding: ""
    property string looking: ""
    // Which of the four carried moves a swap is aimed at, and the move the
    // list is currently reading out. Same rhythm as the food: click to read,
    // click the button to commit.
    property int slot: -1
    // Which shelf the tip along the bottom is describing. A food row says
    // what it is worth and no more; what it *is* goes in the tip, so six
    // shelves are six lines rather than eighteen. Clicking one reveals it,
    // and clicking the revealed one feeds it - look, then commit.
    property string described: ""

    // The one thing this plugin ever has to ask of somebody: a creature that
    // one meal on the shelves right now would evolve. That is a dot on the
    // bar icon and nothing louder - no colour change, no animation.
    // Never while battles are switched off: an evolution is something the
    // game does, and a switched-off game has nothing to ask for.
    readonly property bool wantsAttention: {
        if (!battlesOn) return false
        for (var i = 0; i < rows.length; i++)
            if (rows[i].canEvolveNow) return true
        return false
    }

    // The window a subscreen is about: the one being fed, or the one being
    // read. Both screens are about a single window, so they share the lookup.
    readonly property string subject: feeding !== "" ? feeding : looking
    readonly property var chosen: {
        for (var i = 0; i < rows.length; i++)
            if (String(rows[i].address) === subject) return rows[i]
        // A shut window has no address, so it answers to the name it is
        // remembered under instead.
        for (var j = 0; j < sleepingRows.length; j++)
            if (String(sleepingRows[j].key) === subject) return sleepingRows[j]
        return null
    }

    readonly property bool asleep: !!chosen && chosen.sleeping === true

    // The window's own icon. A creature is its window class, and a class is
    // very nearly a desktop entry, so the lookup is: the entry's icon if
    // there is an entry, the class itself as an icon name if there is not -
    // most applications ship one under their own name - and the last segment
    // of a reverse-DNS class as a final try. Nothing here fails loudly: a
    // window with no icon simply shows its type chip, as it always did.
    function appIcon(key) {
        var name = String(key || "")
        if (name === "") return ""
        var entry = null
        try {
            entry = DesktopEntries.byId(name)
        } catch (e) {
            entry = null
        }
        var candidates = []
        if (entry && entry.icon) candidates.push(String(entry.icon))
        candidates.push(name)
        if (name.indexOf(".") !== -1) candidates.push(name.split(".").pop())
        for (var i = 0; i < candidates.length; i++) {
            var path = Quickshell.iconPath(candidates[i], true)
            if (path && String(path).length > 0) return path
        }
        return ""
    }

    function typeColor(name) {
        var value = typeColors[String(name || "")]
        return value !== undefined ? value : typeColors["GLASS"]
    }

    function alpha(colour, amount) {
        return Qt.rgba(colour.r, colour.g, colour.b, amount)
    }

    // Everything the roster knows about one window, as label/value pairs.
    // The card above already says what it is; this is what it is made of.
    readonly property var stats: {
        var one = chosen
        if (!one) return []
        return [
            { name: "WINS", value: String(one.wins || 0), tone: "#55b364" },
            { name: "LOSSES", value: String(one.losses || 0), tone: "#cc4b4b" },
            { name: "HP", value: String(one.maxHp) },
            { name: "ATTACK", value: String(one.attack) },
            { name: "DEFENSE", value: String(one.defense) },
            { name: "SPEED", value: String(one.speed) },
            { name: "MEALS", value: String(one.meals || 0) },
            { name: "APPETITE", value: one.sleeping ? "none while shut"
                : Number(one.hunger || 0) + " of " + Number(one.appetite || 0) },
            { name: "WINDOWS", value: one.sleeping
                ? "none open" : String(Number(one.count || 1)) },
            // The eldest window's, because that is the one whose age bought
            // the appetite the whole creature eats against.
            { name: "OPEN FOR", value: one.sleeping ? "not open"
                : shortTime(one.uptime) + (Number(one.count || 1) > 1
                                           ? " (eldest)" : "") },
            { name: "EXPERIENCE", value: Number(one.xpNeeded || 0) > 0
                ? Number(one.xpInto || 0) + " / " + Number(one.xpNeeded)
                : "at the cap" },
            { name: "EVOLVES IN", value: Number(one.xpToEvolve || 0) > 0
                ? Number(one.xpToEvolve) + " XP" : "final form" },
            { name: "STAGE", value: Number(one.stage || 1) + " of 3" }
        ]
    }

    readonly property var knownMoves: chosen ? (chosen.moves || []) : []
    readonly property var learnset: chosen ? (chosen.learnset || []) : []

    function carrying(id) {
        for (var i = 0; i < knownMoves.length; i++)
            if (String(knownMoves[i].id) === String(id)) return true
        return false
    }

    function moveFor(id) {
        for (var i = 0; i < learnset.length; i++)
            if (String(learnset[i].id) === String(id)) return learnset[i]
        return null
    }

    function teach(id) {
        if (!chosen || root.slot < 0 || teachProcess.running) return
        teachProcess.command = [root.controlCommand, "teach",
                                String(chosen.address), String(root.slot),
                                String(id), "--json"]
        teachProcess.running = true
    }

    function shortTime(seconds) {
        var value = Number(seconds || 0)
        if (value < 3600) return Math.max(1, Math.round(value / 60)) + "m"
        if (value < 86400) return (value / 3600).toFixed(1) + "h"
        return Math.round(value / 86400) + "d"
    }

    // How long ago something was, for the creatures that are not here now.
    function ago(epoch) {
        var seconds = Date.now() / 1000 - Number(epoch || 0)
        if (!(Number(epoch) > 0) || seconds < 0) return "a while ago"
        if (seconds < 3600) return Math.max(1, Math.round(seconds / 60)) + "m ago"
        if (seconds < 86400) return Math.round(seconds / 3600) + "h ago"
        return Math.round(seconds / 86400) + "d ago"
    }

    function amount(shelf) {
        var value = Number(shelf.available || 0)
        if (shelf.unit === "MiB")
            return value >= 1024 ? (value / 1024).toFixed(1) + " GiB"
                                 : Math.round(value) + " MiB"
        return Math.round(value) + (shelf.unit ? " " + shelf.unit : "")
    }

    // A shelf is servable when the machine has it spare and the creature has
    // room for it. The two refusals read differently on purpose: one is the
    // machine's fault and one is the window's age.
    function servable(shelf) {
        if (!chosen || Number(shelf.servings || 0) <= 0) return false
        return Number(chosen.hunger || 0) >= Number(shelf.nourish || 0)
    }

    function canFeed(row) {
        return !!row && row.canFeed === true && Number(row.hunger || 0) > 0
    }

    // ------------------------------------------------------------- loading

    Process {
        id: rosterProcess
        command: [root.controlCommand, "roster", "--json"]
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.apply(text)
        }
        onExited: root.loading = false
    }

    Process {
        id: feedProcess
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.applyFeed(text)
        }
        onExited: root.refresh()
    }

    Process {
        id: teachProcess
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.applyTeach(text)
        }
        onExited: root.refresh()
    }

    Process {
        id: switchProcess
        command: [root.controlCommand, "toggle"]
        onExited: root.refresh()
    }

    function refresh() {
        if (rosterProcess.running) return
        root.loading = true
        rosterProcess.running = true
    }

    function apply(text) {
        var parsed
        try {
            parsed = JSON.parse(text)
        } catch (e) {
            return              // a daemon mid-restart; the next tick is whole
        }
        root.rows = parsed.roster || []
        root.sleepingRows = parsed.sleeping || []
        root.shelves = parsed.pantry || []
        root.battlesOn = parsed.enabled !== false
        if (root.selected === "" && root.rows.length > 0)
            root.selected = String(root.rows[0].address)
        // The creature being fed has closed: there is nothing to feed, so
        // there is nothing to show.
        if (root.view === "feed" && !root.chosen) root.showRoster()
    }

    function applyTeach(text) {
        var parsed
        try {
            parsed = JSON.parse(text)
        } catch (e) {
            root.note = "The move would not stick."
            return
        }
        root.note = String(parsed.message || "")
        // A swap that took drops you back on the window it was for; a refusal
        // leaves the list up, because the next move along may well be legal.
        if (parsed.ok) root.showWindow(root.subject)
    }

    function applyFeed(text) {
        var parsed
        try {
            parsed = JSON.parse(text)
        } catch (e) {
            root.note = "The meal could not be served."
            return
        }
        root.note = String(parsed.message || "")
        // A served meal takes you back to the list it came from; a refusal
        // stays put, because the next shelf along may well work.
        if (parsed.ok) root.showRoster()
    }

    function feed(shelfKey) {
        if (!chosen || feedProcess.running) return
        feedProcess.command = [root.controlCommand, "feed",
                               String(chosen.address), String(shelfKey),
                               "--json"]
        feedProcess.running = true
    }

    function showRoster() {
        root.view = "roster"
        root.feeding = ""
        root.looking = ""
        root.described = ""
    }

    function showMoves(address, index) {
        root.note = ""
        root.described = ""
        root.feeding = ""
        root.selected = String(address)
        root.looking = String(address)
        root.slot = Number(index)
        root.view = "moves"
    }

    function showWindow(address) {
        root.note = ""
        root.described = ""
        root.feeding = ""
        root.selected = String(address)
        root.looking = String(address)
        root.slot = -1
        root.view = "window"
    }

    function showPantry() {
        root.note = ""
        root.described = ""
        root.feeding = ""
        root.looking = ""
        root.view = "pantry"
    }

    function showFood(address) {
        root.note = ""
        root.described = ""
        root.selected = String(address)
        root.feeding = String(address)
        root.view = "feed"
    }

    // One step out, not all the way: the move list belongs to a window, so
    // its way back is that window rather than the list of all of them.
    function back() {
        if (root.view === "moves" && root.subject !== "")
            root.showWindow(root.subject)
        else if (root.view === "window" && root.asleep)
            root.showSleeping()
        else
            root.showRoster()
    }

    function showSleeping() {
        root.note = ""
        root.described = ""
        root.feeding = ""
        root.looking = ""
        root.view = "sleeping"
    }

    function shelfFor(key) {
        for (var i = 0; i < shelves.length; i++)
            if (String(shelves[i].key) === String(key)) return shelves[i]
        return null
    }

    // Clicking a shelf reads it out; clicking the one already open closes it
    // again. Feeding is never a click on the row - it is the button that
    // appears inside the open one, so nothing is eaten by a second click
    // somebody meant as a second look.
    function touch(key) {
        root.described = (root.described === String(key)) ? "" : String(key)
    }

    // The line along the bottom. It is always there - a tip that comes and
    // goes shifts everything above it every time you read one - and it says
    // the most specific thing there is to say.
    readonly property string tip: {
        var shelf = shelfFor(described)
        if (shelf) {
            var line = String(shelf.name) + ": " + String(shelf.note || "")
            if (view === "feed" && !servable(shelf))
                line += "  Not enough to go round."
            return line
        }
        if (note !== "") return note
        if (view === "roster") return ""
        if (view === "sleeping")
            return "Nothing happens while a window is shut. Open it and it "
                 + "picks up where it left off."
        if (view === "window") {
            if (asleep)
                return "Shut. It keeps its level and its moves; it cannot eat "
                     + "until it is open again."
            return chosen ? String(chosen.title || chosen.name) : ""
        }
        if (view === "moves") {
            var move = moveFor(described)
            if (move) {
                var line = move.name + " - " + move.type + ", power "
                         + move.power + ", " + Math.round(move.accuracy * 100)
                         + "% accurate."
                if (root.carrying(move.id)) line += "  Already carried."
                else if (!move.known) line += "  Learned at level " + move.at + "."
                return line
            }
            return "Swapping slot " + (root.slot + 1) + ". It has to keep two "
                 + "moves of its own type."
        }
        // Nothing open: say what the whole shelf is, because that is the
        // question somebody arriving here has. Short, and only about food.
        return "Spare memory, cycles and dead processes. Appetite grows with "
             + "uptime. Click a food to learn more about it."
    }

    function flip() {
        if (switchProcess.running) return
        // Flip what is drawn straight away: the switch is a file, and waiting
        // for a round trip to show a click is worse than being briefly wrong.
        root.battlesOn = !root.battlesOn
        switchProcess.running = true
    }

    // Open, the roster is worth re-reading often: a window can close while
    // you are looking at the list, and the pantry moves under it.
    Timer {
        interval: 5000
        running: root.opened
        repeat: true
        onTriggered: root.refresh()
    }

    // Shut, it is read slowly and for one reason only: the dot on the icon.
    // Nothing else here matters while nobody is looking, and the window list,
    // /proc and the pantry are cheap but not free.
    Timer {
        interval: 60000
        running: !root.opened
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    onOpenedChanged: if (opened) {
        note = ""
        showRoster()
        refresh()
        Qt.callLater(function () { keyCatcher.forceActiveFocus() })
    }

    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    IpcHandler {
        target: root.ipcTarget
        function open(): void { root.open() }
        function close(): void { root.close() }
        function toggle(): void { root.toggle() }
        function refresh(): string { root.refresh(); return "ok" }
        // The two inner views, for working on them without a mouse - the same
        // reason Battle.qml carries `debugBattle`.
        function pantry(): string { root.open(); root.showPantry(); return "ok" }
        function moves(address: string, slot: string): string {
            root.open()
            root.showMoves(address, Number(slot))
            return "ok"
        }
        function asleep(): string { root.open(); root.showSleeping(); return "ok" }
        function details(address: string): string {
            root.open()
            root.showWindow(address)
            return "ok"
        }
        function describe(key: string): string { root.touch(key); return root.tip }
        function food(address: string): string {
            root.open()
            root.showFood(address)
            return "ok"
        }
    }

    component WindowCard: Rectangle {
        id: creature

        property var row: ({})
        property bool interactive: true
        readonly property bool picked:
            interactive && String(row.address) === root.selected
        readonly property color tint: root.typeColor(row.type)
        readonly property real fullness:
            Number(row.appetite || 1) > 0
                ? Number(row.hunger || 0) / Number(row.appetite)
                : 0
        readonly property bool feedable: root.canFeed(row)

        height: card.height + Style.spacing.md * 2
        radius: Style.cornerRadius
        // Every creature lives in a box of its own: a list
        // of bare rows on a panel this busy reads as one
        // paragraph rather than six things. The box is
        // only an outline - a filled card would fight the
        // panel's own surface, and the type colour is the
        // only fill on a creature that means anything.
        // Lit only under the pointer, and only where there is somewhere to
        // go: a card is a door to the window's own page.
        color: (cardMouse.containsMouse && creature.interactive)
            ? Style.selectedFillFor(root.foreground, Color.accent)
            : "transparent"
        border.width: Math.max(1, Style.space(1))
        border.color: picked ? root.alpha(creature.tint, 0.65)
                             : Style.normalBorderColor

        MouseArea {
            id: cardMouse
            anchors.fill: parent
            hoverEnabled: true
            enabled: creature.interactive
            cursorShape: Qt.PointingHandCursor
            onClicked: root.showWindow(creature.row.sleeping
                                       ? creature.row.key
                                       : creature.row.address)
        }

        Row {
            id: card
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: Style.spacing.md
            anchors.leftMargin: Style.spacing.md
            anchors.rightMargin: Style.spacing.rowPaddingX
            spacing: Style.spacing.xxl

            Column {
                width: parent.width - feedButton.width
                       - (feedButton.visible ? Style.spacing.xxl : 0)
                spacing: Style.spacing.xs

                Row {
                    width: parent.width
                    spacing: Style.spacing.sm

                    // The type, as the colour it fights as.
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: typeLabel.implicitWidth + Style.spacing.md * 2
                        height: typeLabel.implicitHeight + Style.spacing.xs * 2
                        radius: Style.cornerRadius
                        color: creature.tint

                        Text {
                            id: typeLabel
                            anchors.centerIn: parent
                            text: String(creature.row.type || "")
                            color: "#111111"
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                            font.bold: true
                        }
                    }

                    // The creature's face: an agent wears the mark
                    // Omarchy already gives it, everything else its own
                    // desktop icon. Each candidate is tried in turn and
                    // the glyph is what is left when none of them loaded.
                    Item {
                        id: mark
                        anchors.verticalCenter: parent.verticalCenter
                        // Both from the row and never from the picture:
                        // sizing a slot by whether its image loaded, while
                        // the image is sized by the slot, is a binding loop
                        // the shell says so out loud.
                        width: visible ? Style.font.heading : 0
                        height: Style.font.heading
                        visible: sources.length > 0 || markLetter.text !== ""

                        readonly property var sources:
                            root.markSources(creature.row)
                        property int attempt: 0
                        // A card is reused as the list scrolls, so the
                        // walk starts again whenever the row changes.
                        onSourcesChanged: attempt = 0

                        Image {
                            id: markImage
                            anchors.fill: parent
                            visible: status === Image.Ready
                            fillMode: Image.PreserveAspectFit
                            // Decode at physical pixels, or a
                            // PNG icon is upscaled and blurry
                            // on a HiDPI screen.
                            sourceSize.width: Math.round(width * Screen.devicePixelRatio)
                            sourceSize.height: Math.round(width * Screen.devicePixelRatio)
                            source: mark.attempt < mark.sources.length
                                    ? mark.sources[mark.attempt] : ""
                            onStatusChanged: if (status === Image.Error
                                                 && mark.attempt < mark.sources.length)
                                                 mark.attempt++
                        }

                        Text {
                            id: markLetter
                            anchors.centerIn: parent
                            visible: !markImage.visible && text !== ""
                            text: root.markGlyph(creature.row)
                            color: creature.tint
                            font.family: root.markGlyphFont(creature.row)
                            font.pixelSize: Style.font.heading
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(creature.row.name || "")
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.bold: true
                    }

                    // Two Braves are one creature with two windows open, not
                    // two creatures: everything on this card but the count
                    // is the same number for both of them.
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: Number(creature.row.count || 1) > 1
                        text: "\u00d7" + Number(creature.row.count || 1)
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        font.bold: true
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        // Stars are the stage: one per
                        // evolution it has been through,
                        // and none for one that has not.
                        text: "\u2605\u2605".substring(0, Math.max(0, Number(creature.row.stage || 1) - 1))
                        color: creature.tint
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                    }
                }

                Text {
                    width: parent.width
                    elide: Text.ElideRight
                    text: "LV " + Number(creature.row.level || 0)
                          + (creature.row.sleeping
                             ? "   last up " + root.ago(creature.row.seen)
                             : "   up " + root.shortTime(creature.row.uptime))
                          + (Number(creature.row.xpNeeded || 0) > 0
                             ? "   " + Number(creature.row.xpInto || 0)
                               + "/" + Number(creature.row.xpNeeded) + " XP"
                             : "   MAX")
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }

                // How much it can still eat. It empties as
                // the creature is fed and fills again as
                // the window ages, which is the whole of
                // the hunger rule drawn as one bar.
                Rectangle {
                    // An appetite bar means nothing without a window to be
                    // hungry with.
                    visible: !creature.row.sleeping
                    width: parent.width
                    height: visible ? Math.max(2, Style.space(4)) : 0
                    radius: height / 2
                    color: root.alpha(root.foreground, 0.16)

                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(1, creature.fullness))
                        height: parent.height
                        radius: parent.radius
                        color: creature.tint
                        Behavior on width { NumberAnimation { duration: 180 } }
                    }
                }

                Text {
                    width: parent.width
                    text: creature.row.sleeping
                        ? "Shut - it keeps its level and its moves"
                        : (creature.row.canEvolveNow
                           ? "One meal from evolving"
                           : Number(creature.row.hunger || 0) + " of "
                             + Number(creature.row.appetite || 0)
                             + " appetite left")
                    color: (creature.row.canEvolveNow && !creature.row.sleeping)
                        ? creature.tint : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }
            }

            // The one action a card has. It opens the
            // pantry for this creature rather than feeding
            // it something chosen for you: what is worth
            // eating depends on what the machine has, and
            // that is a list, not a button.
            Rectangle {
                id: feedButton

                anchors.verticalCenter: parent.verticalCenter
                // The card pinned above the food picker is a reminder of what
                // you are feeding, not a second way to start feeding it - and
                // a shut window has nothing to be fed with at all.
                visible: creature.interactive && !creature.row.sleeping
                width: visible ? feedLabel.implicitWidth + Style.spacing.lg * 2 : 0
                height: feedLabel.implicitHeight + Style.spacing.md * 2
                radius: Style.cornerRadius
                opacity: creature.feedable ? 1.0 : 0.40
                // Plain, and the same on every card. The
                // type colour means "what this window
                // fights as"; a button wearing it would
                // be saying something it does not mean.
                color: feedMouse.containsMouse && creature.feedable
                    ? Style.selectedFillFor(root.foreground, Color.accent)
                    : root.alpha(root.foreground, 0.08)
                border.width: Math.max(1, Style.space(1))
                border.color: Style.normalBorderColor

                MouseArea {
                    id: feedMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: creature.feedable
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.showFood(creature.row.address)
                }

                Text {
                    id: feedLabel
                    anchors.centerIn: parent
                    text: "󱁂  Feed"
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }
            }
        }
    }

    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        // Crossed swords, the same glyph the Omarchy menu row carries, so the
        // two ways to the switch look like the same thing.
        text: "󰞇"
        // Never the urgent colour. An icon that goes red for a state the
        // person chose - battles being on - cries wolf all day. Off is grey,
        // on is the bar's own colour, and the only thing that ever stands out
        // is the dot.
        active: false
        useActiveColor: false
        foreground: root.battlesOn
            ? (root.bar ? root.bar.barForeground : Color.foreground)
            : root.alpha(root.bar ? root.bar.barForeground : Color.foreground, 0.40)
        tooltipText: root.battlesOn
            ? (root.wantsAttention
                ? "Window battles are on\nsomething is one meal from evolving"
                : "Window battles are on\nclick for the roster")
            : "Window battles are off\nclick for the roster"
        onPressed: root.toggle()

        // The notification dot: the same red the HP bar wears when a creature
        // is in trouble, because it means the same kind of thing - look here.
        Rectangle {
            visible: root.wantsAttention
            width: Math.max(4, Style.space(6))
            height: width
            radius: width / 2
            color: "#cc4b4b"
            x: parent.width - width - Math.max(1, Style.space(2))
            y: Math.max(1, Style.space(3))
        }
    }

    KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        padding: 0
        contentWidth: panel.fittedContentWidth(Style.space(360))
        // The scrolling list is only part of the height now: the sticky head
        // and the tip are outside it, and a panel measured on the list alone
        // squeezes the list to make room for them.
        contentHeight: panel.fittedContentHeight(
            column.implicitHeight
            + (head.visible ? head.height + root.pageTop + Style.spacing.md : 0)
            + (tipBar.visible ? tipBar.height + root.pagePad : 0)
            + (feedBar.visible ? feedBar.height + Style.spacing.md : 0)
            // The last few pixels of the food, which the measurement above is
            // shy of - without them the grid scrolls by a sliver, which is
            // worse than the sliver of extra panel.
            + (root.view === "roster" ? 0 : Style.space(6)),
            // The food is a fixed, short list and a two-column grid of it
            // fits on one screen, so the picker is allowed the height that
            // keeps it there. The list of windows is as long as your desktop
            // is, so that one stays capped.
            Style.space(root.view === "roster" ? 620 : 700))

        PanelKeyCatcher {
            id: keyCatcher
            anchors.fill: parent

            onMoveRequested: function (dx, dy) {
                if (dy !== 0 && root.view === "roster" && root.rows.length > 0) {
                    var index = 0
                    for (var i = 0; i < root.rows.length; i++)
                        if (String(root.rows[i].address) === root.selected) index = i
                    index = Math.max(0, Math.min(root.rows.length - 1, index + dy))
                    root.selected = String(root.rows[index].address)
                }
            }
            onActivateRequested: {
                if (root.view === "roster" && root.selected !== "")
                    root.showWindow(root.selected)
                else
                    root.refresh()
            }
            // Escape steps back out of a view before it closes the panel:
            // one key, the way out of wherever you are.
            onCloseRequested: root.view === "roster" ? root.close() : root.back()
            onTabRequested: function (direction) { root.switchPanel(direction) }
            onTextKey: function (key) { if (key === "b" || key === "B") root.flip() }

            // The subscreens keep their way out - and, in the food picker,
            // the window being fed - pinned above the list. Both answer
            // "where am I", which is not a question a scrolled list should be
            // able to take off the screen.
            Column {
                id: head

                anchors.top: parent.top
                anchors.topMargin: root.pageTop
                x: root.pagePad + flick.gutter / 2
                width: flick.width - root.pagePad * 2 - flick.gutter
                spacing: Style.spacing.md
                visible: root.view !== "roster"

                Rectangle {
                    width: parent.width
                    height: backLabel.implicitHeight + Style.spacing.md * 2
                    radius: Style.cornerRadius
                    color: backMouse.containsMouse
                        ? Style.selectedFillFor(root.foreground, Color.accent)
                        : "transparent"
                    border.width: Math.max(1, Style.space(1))
                    border.color: Style.normalBorderColor

                    MouseArea {
                        id: backMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.back()
                    }

                    Text {
                        id: backLabel
                        anchors.centerIn: parent
                        text: root.view === "moves" && !!root.chosen
                            ? "  Back to " + String(root.chosen.name)
                            : (root.view === "window" && root.asleep
                               ? "  Back to the sleeping"
                               : "  Back to the windows")
                        color: root.foreground
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                    }
                }

                PanelSeparator {
                    visible: root.view !== "pantry" && root.view !== "sleeping"
                             && !!root.chosen
                    width: parent.width
                }

                // What you are feeding, above its food: the picker is a list
                // long enough to scroll, and a window is easy to lose track of
                // halfway down somebody else's dinner. A card like any other,
                // minus the button - you are already feeding it.
                WindowCard {
                    visible: root.view !== "pantry" && root.view !== "sleeping"
                             && !!root.chosen
                    width: parent.width
                    row: root.chosen || ({})
                    interactive: false
                }
            }

            Flickable {
                id: flick
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: head.visible ? head.bottom : parent.top
                anchors.topMargin: head.visible ? Style.spacing.md : 0
                anchors.bottom: feedBar.visible ? feedBar.top : tipBar.top
                anchors.bottomMargin: root.view === "roster" ? 0 : Style.spacing.md
                contentWidth: width
                contentHeight: column.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.VerticalFlick
                interactive: contentHeight > height
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    parent: flick
                    anchors.right: flick.right
                    anchors.top: flick.top
                    anchors.bottom: flick.bottom
                }

                // A gutter for the scrollbar, and only while there is one: a
                // bar drawn over the right-hand edge of a card clips the thing
                // it is there to help you read. It is split between the two
                // sides, because taking it all off the right would leave the
                // list visibly off-centre in its own panel.
                readonly property int gutter: flick.interactive ? Style.space(16) : 0

                Column {
                    id: column
                    x: root.pagePad + flick.gutter / 2
                    width: flick.width - root.pagePad * 2 - flick.gutter
                    spacing: Style.spacing.md

                    // The top margin is part of the page rather than part of
                    // the panel, so it scrolls away with everything else
                    // instead of leaving a gap the list slides under.
                    Item {
                        width: 1
                        visible: !head.visible
                        height: visible ? root.pageTop - column.spacing : 0
                    }

                    // ------------------------------------------- the switch

                    Toggle {
                        // The switch is the list's own header. Carrying it
                        // into the food would be offering to turn the game
                        // off from inside a menu about dinner.
                        visible: root.view === "roster"
                        width: parent.width
                        label: "Window battles"
                        description: root.battlesOn
                            ? "A collided move rolls one in four"
                            : "Moves are only moves"
                        checked: root.battlesOn
                        foreground: root.foreground
                        fontFamily: root.fontFamily
                        onClicked: root.flip()
                    }

                    // The two ways out of the list, at the top where they
                    // can be seen and side by side because they are the same
                    // kind of thing: a step sideways into another screen,
                    // each with a chevron to say so. Sleeping on the left,
                    // because it is about the windows this screen is about;
                    // food on the right, because it is about the machine.
                    Row {
                        visible: root.view === "roster"
                        width: parent.width
                        spacing: Style.spacing.md

                        Rectangle {
                            id: sleepDoor

                            width: (parent.width - Style.spacing.md) / 2
                            height: sleepLabel.implicitHeight + Style.spacing.md * 2
                            radius: Style.cornerRadius
                            color: sleepMouse.containsMouse
                                ? Style.selectedFillFor(root.foreground, Color.accent)
                                : "transparent"
                            border.width: Math.max(1, Style.space(1))
                            border.color: Style.normalBorderColor

                            MouseArea {
                                id: sleepMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.showSleeping()
                            }

                            Text {
                                id: sleepLabel
                                anchors.left: parent.left
                                anchors.leftMargin: Style.spacing.md
                                anchors.verticalCenter: parent.verticalCenter
                                text: "󰖔  Sleeping"
                                color: root.foreground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.body
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: Style.spacing.md
                                anchors.verticalCenter: parent.verticalCenter
                                text: ""
                                color: root.dim
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                            }
                        }

                        Rectangle {
                            id: foodDoor

                            width: (parent.width - Style.spacing.md) / 2
                            height: foodLabel.implicitHeight + Style.spacing.md * 2
                            radius: Style.cornerRadius
                            color: foodMouse.containsMouse
                                ? Style.selectedFillFor(root.foreground, Color.accent)
                                : "transparent"
                            border.width: Math.max(1, Style.space(1))
                            border.color: Style.normalBorderColor

                            MouseArea {
                                id: foodMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.showPantry()
                            }

                            Text {
                                id: foodLabel
                                anchors.left: parent.left
                                anchors.leftMargin: Style.spacing.md
                                anchors.verticalCenter: parent.verticalCenter
                                text: "󱁂  All food"
                                color: root.foreground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.body
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: Style.spacing.md
                                anchors.verticalCenter: parent.verticalCenter
                                text: ""
                                color: root.dim
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                            }
                        }
                    }

                    PanelSeparator { width: parent.width }

                    PanelSectionHeader {
                        width: parent.width
                        text: root.view === "roster" ? "WINDOWS"
                            : (root.view === "sleeping" ? "SLEEPING WINDOWS"
                               : root.view === "pantry" ? "ALL FOOD"
                               : (root.view === "moves"
                                  ? "SLOT " + (root.slot + 1)
                                  : root.view === "window" ? "THE RECORD"
                                  : "FEED " + (root.chosen ? String(root.chosen.name) : "")))
                        foreground: root.foreground
                        fontFamily: root.fontFamily
                    }

                    // ------------------------------------------ the roster

                    Text {
                        visible: root.view === "sleeping"
                                 && root.sleepingRows.length === 0
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "Nothing is asleep. A window turns up here once "
                              + "it has been open with battles running and is "
                              + "then closed."
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                    }

                    Text {
                        visible: root.view === "roster" && root.rows.length === 0
                        width: parent.width
                        text: root.loading ? "Counting windows..." : "No windows open."
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                    }

                    Repeater {
                        model: root.view === "roster" ? root.rows
                             : (root.view === "sleeping" ? root.sleepingRows : [])

                        WindowCard {
                            row: modelData
                            width: column.width
                        }
                    }

                    // ------------------------------------ one window, in full
                    //
                    // The card at the top says what it is; this says what it
                    // is made of. Two columns, because every line is a short
                    // label and a shorter number.

                    Grid {
                        visible: root.view === "window" && !!root.chosen
                        columns: 2
                        columnSpacing: Style.spacing.md
                        rowSpacing: Style.spacing.md
                        width: parent.width

                        Repeater {
                            model: root.view === "window" ? root.stats : []

                            Rectangle {
                                id: stat

                                required property var modelData

                                width: (column.width - Style.spacing.md) / 2
                                height: statBody.implicitHeight + Style.spacing.md * 2
                                radius: Style.cornerRadius
                                color: "transparent"
                                border.width: Math.max(1, Style.space(1))
                                border.color: Style.normalBorderColor

                                Column {
                                    id: statBody
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: Style.spacing.md
                                    spacing: Style.spacing.xxs

                                    Text {
                                        width: parent.width
                                        elide: Text.ElideRight
                                        text: String(stat.modelData.name)
                                        color: root.dim
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.caption
                                    }

                                    Text {
                                        width: parent.width
                                        elide: Text.ElideRight
                                        text: String(stat.modelData.value)
                                        color: stat.modelData.tone
                                            ? stat.modelData.tone : root.foreground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.body
                                    }
                                }
                            }
                        }
                    }

                    PanelSectionHeader {
                        visible: root.view === "window" && root.knownMoves.length > 0
                        width: parent.width
                        text: "MOVES"
                        foreground: root.foreground
                        fontFamily: root.fontFamily
                    }

                    // What it fights with, and the colour each move belongs
                    // to - the same eight the arena uses, so a move borrowed
                    // from another type is visible as one at a glance.
                    Grid {
                        visible: root.view === "window"
                        columns: 2
                        columnSpacing: Style.spacing.md
                        rowSpacing: Style.spacing.md
                        width: parent.width

                        Repeater {
                            model: root.view === "window" ? root.knownMoves : []

                            Rectangle {
                                id: move

                                required property var modelData
                                required property int index
                                readonly property color tint: root.typeColor(modelData.type)

                                width: (column.width - Style.spacing.md) / 2
                                height: moveBody.implicitHeight + Style.spacing.md * 2
                                radius: Style.cornerRadius
                                color: moveMouse.containsMouse
                                    ? root.alpha(move.tint, 0.26)
                                    : root.alpha(move.tint, 0.10)
                                border.width: Math.max(1, Style.space(1))
                                border.color: root.alpha(move.tint, 0.45)

                                // Each of the four is a slot: click it and
                                // the list of everything known opens on it.
                                MouseArea {
                                    id: moveMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.showMoves(root.subject, move.index)
                                }

                                Column {
                                    id: moveBody
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: Style.spacing.md
                                    spacing: Style.spacing.xxs

                                    Text {
                                        width: parent.width
                                        elide: Text.ElideRight
                                        text: String(move.modelData.name || "")
                                        color: root.foreground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.body
                                    }

                                    Text {
                                        width: parent.width
                                        text: String(move.modelData.type || "")
                                              + " - power " + Number(move.modelData.power || 0)
                                        color: root.dim
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.caption
                                    }
                                }
                            }
                        }
                    }

                    // ------------------------------------------- the moves
                    //
                    // Everything this creature knows, and everything it has
                    // yet to learn, with the level it arrives at. A list that
                    // shows only what you have is a list that never tells you
                    // to keep going.

                    Grid {
                        visible: root.view === "moves"
                        columns: 2
                        columnSpacing: Style.spacing.md
                        rowSpacing: Style.spacing.md
                        width: parent.width

                        Repeater {
                            model: root.view === "moves" ? root.learnset : []

                            Rectangle {
                                id: known

                                required property var modelData
                                readonly property color tint: root.typeColor(modelData.type)
                                readonly property bool carried: root.carrying(modelData.id)
                                readonly property bool reading:
                                    root.described === String(modelData.id)
                                readonly property bool pickable:
                                    modelData.known && !carried

                                width: (column.width - Style.spacing.md) / 2
                                height: knownBody.implicitHeight + Style.spacing.md * 2
                                radius: Style.cornerRadius
                                opacity: modelData.known ? 1.0 : 0.45
                                color: (knownMouse.containsMouse || reading)
                                    ? root.alpha(known.tint, 0.26)
                                    : root.alpha(known.tint, 0.10)
                                border.width: Math.max(1, Style.space(1))
                                border.color: carried
                                    ? root.alpha(known.tint, 0.85)
                                    : root.alpha(known.tint, 0.45)

                                MouseArea {
                                    id: knownMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.described =
                                        (root.described === String(known.modelData.id))
                                        ? "" : String(known.modelData.id)
                                }

                                Column {
                                    id: knownBody
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: Style.spacing.md
                                    spacing: Style.spacing.xxs

                                    Text {
                                        width: parent.width
                                        elide: Text.ElideRight
                                        text: String(known.modelData.name || "")
                                        color: root.foreground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.body
                                    }

                                    Text {
                                        width: parent.width
                                        elide: Text.ElideRight
                                        text: known.carried
                                            ? "carried - power " + Number(known.modelData.power || 0)
                                            : (known.modelData.known
                                               ? "power " + Number(known.modelData.power || 0)
                                               : "learns at LV " + Number(known.modelData.at || 0))
                                        color: root.dim
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.caption
                                    }
                                }
                            }
                        }
                    }

                    // -------------------------------------------- the food
                    //
                    // The same shelves in both of the other two views. In the
                    // feed view they are buttons and say what this creature
                    // would get out of them; in the pantry view they are a
                    // reading of the machine and nothing more.

                    // Two columns, not seven rows. The pantry is a fixed,
                    // short list and every shelf is two short facts, so a
                    // grid puts the whole machine on one screen - no scroll
                    // between you and the food.
                    Grid {
                        // The food, and only on the two screens that are
                        // about food. A window's own page has its own.
                        readonly property bool showing:
                            root.view === "feed" || root.view === "pantry"

                        visible: showing
                        columns: 2
                        columnSpacing: Style.spacing.md
                        rowSpacing: Style.spacing.md
                        width: parent.width

                        Repeater {
                            model: parent.showing ? root.shelves : []

                            Rectangle {
                                id: shelf

                                required property var modelData
                                readonly property bool picking: root.view === "feed"
                                readonly property bool ready: picking && root.servable(modelData)
                                readonly property bool reading:
                                    root.described === String(modelData.key)

                                width: (column.width - Style.spacing.md) / 2
                                height: shelfBody.implicitHeight + Style.spacing.md * 2
                                radius: Style.cornerRadius
                                color: (shelfMouse.containsMouse || reading)
                                    ? Style.selectedFillFor(root.foreground, Color.accent)
                                    : "transparent"
                                border.width: Math.max(1, Style.space(1))
                                border.color: reading
                                    ? Style.selectedBorderColor : Style.normalBorderColor
                                opacity: (!picking || ready) ? 1.0 : 0.45

                                MouseArea {
                                    id: shelfMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.touch(shelf.modelData.key)
                                }

                                Column {
                                    id: shelfBody
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: Style.spacing.md
                                    spacing: Style.spacing.xxs

                                    Row {
                                        width: parent.width
                                        spacing: Style.spacing.sm

                                        Text {
                                            id: shelfName
                                            width: parent.width - shelfWorth.implicitWidth
                                                   - Style.spacing.sm
                                            elide: Text.ElideRight
                                            text: String(shelf.modelData.name || "")
                                            color: root.foreground
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.body
                                        }

                                        Text {
                                            id: shelfWorth
                                            anchors.baseline: shelfName.baseline
                                            text: "+" + Number(shelf.modelData.nourish || 0)
                                            color: root.dim
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.caption
                                        }
                                    }

                                    Text {
                                        width: parent.width
                                        elide: Text.ElideRight
                                        text: Number(shelf.modelData.servings || 0)
                                              + " servings"
                                        color: root.dim
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.caption
                                    }
                                }
                            }
                        }
                    }

                    Item {
                        visible: root.view === "roster"
                        width: 1
                        height: visible ? root.pagePad - column.spacing : 0
                    }
                }
            }

            // The one button, and it is pinned above the tip rather than
            // left at the end of the grid: what you picked and what you do
            // with it should not be able to scroll apart. A cell this narrow
            // could hold two facts or one button, and the two facts are what
            // you are choosing on.
            Rectangle {
                id: feedBar

                readonly property var shelf: root.shelfFor(root.described)
                // On a window's own page the button is the way to its food;
                // in the picker it is the meal itself.
                readonly property bool onWindow: root.view === "window"
                readonly property bool onMoves: root.view === "moves"
                readonly property var move: onMoves ? root.moveFor(root.described) : null
                readonly property bool ready: onWindow
                    ? root.canFeed(root.chosen)
                    : (onMoves
                       ? (!!move && move.known && !root.carrying(move.id))
                       : (!!shelf && root.servable(shelf)))

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: tipBar.top
                anchors.leftMargin: root.pagePad + flick.gutter / 2
                anchors.rightMargin: root.pagePad + flick.gutter / 2
                anchors.bottomMargin: visible ? Style.spacing.md : 0
                visible: (root.view === "feed" && !!shelf)
                         || (onWindow && !!root.chosen && !root.asleep)
                         || (onMoves && !!move)
                height: visible ? feedBarLabel.implicitHeight + Style.spacing.md * 2 : 0
                radius: Style.cornerRadius
                opacity: ready ? 1.0 : 0.40
                color: feedBarMouse.containsMouse && ready
                    ? Style.selectedFillFor(root.foreground, Color.accent)
                    : root.alpha(root.foreground, 0.08)
                border.width: visible ? Math.max(1, Style.space(1)) : 0
                border.color: Style.normalBorderColor

                MouseArea {
                    id: feedBarMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: feedBar.ready
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (feedBar.onWindow) root.showFood(root.subject)
                        else if (feedBar.onMoves) root.teach(root.described)
                        else root.feed(root.described)
                    }
                }

                Text {
                    id: feedBarLabel
                    anchors.centerIn: parent
                    text: feedBar.onMoves
                        ? ("Teach " + (feedBar.move ? String(feedBar.move.name) : "")
                           + " into slot " + (root.slot + 1))
                        : ("󱁂  Feed " + (feedBar.onWindow
                           ? (root.chosen ? String(root.chosen.name) : "")
                           : (feedBar.shelf ? String(feedBar.shelf.name) : "")))
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                }
            }

            // The tip. Pinned to the bottom of the panel rather than to the
            // end of the list: it is the one line that answers "what is this
            // thing", and a line you have to scroll to find cannot do that.
            Rectangle {
                id: tipBar

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: root.pagePad
                anchors.rightMargin: root.pagePad
                // Nothing at all when there is no tip: a margin held open by
                // an invisible strip is a gap the list cannot scroll into.
                anchors.bottomMargin: visible ? root.pagePad - Style.spacing.sm : 0
                // The list of windows says what it is on every row; a line
                // under it would be repeating itself. The tip belongs to the
                // food views, where the rows are deliberately terse.
                visible: root.view !== "roster"
                // The text measures itself and the strip follows it. Filling
                // the strip with the text instead makes the two chase each
                // other, which Qt reports as a binding loop.
                height: visible ? tipText.height + Style.spacing.sm * 2 : 0
                // No box. It sits under everything that scrolls, and a framed
                // strip down there reads as a second panel rather than as the
                // footnote it is.
                color: "transparent"

                Text {
                    id: tipText
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: Style.spacing.sm
                    anchors.rightMargin: Style.spacing.sm
                    anchors.topMargin: Style.spacing.sm
                    wrapMode: Text.WordWrap
                    text: root.tip
                    color: root.alpha(root.foreground, 0.75)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                }
            }
        }
    }
}
