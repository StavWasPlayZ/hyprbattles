// Runs the battles daemon (bin/battles) for as long as this plugin is
// enabled, and puts the battle screen up (Battle.qml). The bar widget is a
// separate entry point, BattlesToggle.qml.
//
// The daemon is a plain Python process, not QML: it listens on Hyprland's
// event socket for the gamepad plugin's collision report, rolls the odds,
// borrows the controller and runs the fight. Everything this plugin needs
// from the other two goes through public interfaces - Hyprland's own event
// and command sockets, and the gamepad plugin's lending API - so a missing
// neighbour means no battles rather than an error.

import QtQuick
import Quickshell.Io

Item {
    id: root

    readonly property string daemonPath: decodeURIComponent(
        Qt.resolvedUrl("bin/battles").toString().replace(/^file:\/\//, "")
    )

    // The battle screen. It draws only while the daemon says a battle is on,
    // and does nothing at all otherwise.
    Battle {}

    Process {
        id: daemon

        command: [root.daemonPath]
        running: true

        onExited: function(exitCode) {
            if (exitCode !== 0) console.warn("Battles: daemon exited with", exitCode)
            restart.restart()
        }

        stderr: SplitParser {
            onRead: function(line) { console.warn("Battles:", line) }
        }
    }

    // A Hyprland restart can take the daemon down with it; bring it back,
    // slowly enough that a broken one cannot spin.
    Timer {
        id: restart
        interval: 3000
        onTriggered: daemon.running = true
    }
}
