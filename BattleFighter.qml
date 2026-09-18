// One fighter on the battle screen: the live window, the platform it stands
// on, and the flinch when it is hit. Part of Battle.qml; see docs/BATTLES.md.
//
// The creature is the window itself, captured live with a ScreencopyView, so
// it keeps running while it fights - a terminal scrolls, a video plays. The
// window is never moved, resized, floated or re-parented to put it here; this
// is a view of it, which is why a battle cannot cost anyone a window.

import QtQuick
import Quickshell.Wayland
import qs.Commons

Item {
    id: root

    property var creature: ({})
    property var toplevel: null
    property int unit: 3
    property int frameWidth: 2
    property color tint: "#5f9ea0"
    // Where this fighter slides in from at the start of the battle. The slide
    // is a transform rather than an animation on `x`: animating x directly
    // would overwrite the binding that positions the fighter, and it would
    // stay wherever the animation left it.
    property real entryFrom: 0
    property real slide: 0

    transform: Translate { x: root.slide }
    // Raised by Battle.qml for the side that was just hit; `pulse` changes on
    // every snapshot, so a second hit in a row still plays.
    property bool struck: false
    property bool fainted: false
    property int pulse: 0

    property int lastPulse: -1

    onPulseChanged: {
        if (root.struck && root.pulse !== root.lastPulse) {
            root.lastPulse = root.pulse
            flinch.restart()
        }
    }

    // The ground: an ellipse just below the window, wide enough to read as a
    // platform without covering any of the window itself.
    Rectangle {
        width: parent.width * 1.12
        height: parent.height * 0.15
        x: -parent.width * 0.06
        y: parent.height - height * 0.42
        radius: height / 2
        color: Util.alpha(Color.accent, 0.18)
        border.width: Math.max(1, Math.round(root.frameWidth / 2))
        border.color: Util.alpha(Color.accent, 0.45)
    }

    Item {
        id: body

        anchors.fill: parent
        opacity: root.fainted ? 0.0 : 1.0
        y: root.fainted ? parent.height * 0.28 : 0

        Behavior on opacity { NumberAnimation { duration: 520 } }
        Behavior on y { NumberAnimation { duration: 520; easing.type: Easing.InQuad } }

        Rectangle {
            anchors.fill: parent
            anchors.margins: -root.frameWidth * 2
            color: Util.alpha(Color.background, 0.55)
            border.width: root.frameWidth * 2
            border.color: Util.alpha(Color.foreground, 0.80)
        }

        ScreencopyView {
            id: view

            anchors.centerIn: parent
            captureSource: root.toplevel
            live: true
            paintCursor: false

            readonly property real ratio: (sourceSize.width > 0 && sourceSize.height > 0)
                ? sourceSize.width / sourceSize.height : 16 / 9
            width: Math.min(parent.width - root.frameWidth * 2,
                            (parent.height - root.frameWidth * 2) * ratio)
            height: width / ratio
        }

        // A window that cannot be captured - it closed, or the compositor
        // refused - still gets a body to fight in.
        Rectangle {
            anchors.fill: parent
            anchors.margins: root.frameWidth
            visible: !view.hasContent
            color: Util.alpha(root.tint, 0.5)

            PixelText {
                anchors.centerIn: parent
                text: String(root.creature.name || "")
                pixel: root.unit
                color: Color.foreground
            }
        }

        Rectangle {
            id: flash
            anchors.fill: parent
            color: Color.foreground
            opacity: 0
        }
    }

    SequentialAnimation {
        id: flinch

        ParallelAnimation {
            NumberAnimation {
                target: flash; property: "opacity"
                from: 0.8; to: 0.0; duration: 340
            }
            SequentialAnimation {
                NumberAnimation { target: body; property: "x"; to: root.unit * 5; duration: 45 }
                NumberAnimation { target: body; property: "x"; to: -root.unit * 5; duration: 60 }
                NumberAnimation { target: body; property: "x"; to: root.unit * 3; duration: 55 }
                NumberAnimation { target: body; property: "x"; to: 0; duration: 70 }
            }
        }
    }

    // The entrance. Driven from Battle.qml rather than from `visible`, so it
    // runs once per battle instead of once per property change.
    function enter() {
        entry.restart()
    }

    NumberAnimation {
        id: entry
        target: root
        property: "slide"
        from: root.entryFrom
        to: 0
        duration: 560
        easing.type: Easing.OutCubic
    }
}
