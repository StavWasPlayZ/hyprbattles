// One fighter's name plate: name, level, type and the HP bar. Part of the
// battle screen (Battle.qml); see docs/BATTLES.md.
//
// The box itself follows the theme, so it is readable on a light desktop and
// a dark one. The bar does not: green, amber and red have to mean the same
// thing everywhere, and a themed HP bar would be a worse HP bar.

import QtQuick
import qs.Commons

Rectangle {
    id: root

    property var creature: ({})
    property int unit: 3
    property int frameWidth: 2
    property bool showNumbers: false
    property color tint: "#5f9ea0"

    readonly property int hp: Number(creature.hp || 0)
    readonly property int maxHp: Math.max(1, Number(creature.maxHp || 1))
    readonly property real fraction: Math.max(0, Math.min(1, hp / maxHp))

    height: column.implicitHeight + unit * 10
    color: Util.alpha(Color.background, 0.92)
    border.width: frameWidth
    border.color: Util.alpha(Color.foreground, 0.85)

    // The inner hairline that gives a chunky box its depth.
    Rectangle {
        anchors.fill: parent
        anchors.margins: root.frameWidth * 2
        color: "transparent"
        border.width: Math.max(1, Math.round(root.frameWidth / 2))
        border.color: Util.alpha(Color.foreground, 0.22)
    }

    Column {
        id: column

        x: root.unit * 5
        y: root.unit * 5
        width: parent.width - root.unit * 10
        spacing: root.unit * 3

        Item {
            width: parent.width
            height: Math.max(nameText.implicitHeight, levelText.implicitHeight)

            PixelText {
                id: nameText
                text: String(root.creature.name || "")
                pixel: root.unit
                color: Color.foreground
            }

            PixelText {
                id: levelText
                anchors.right: parent.right
                text: "LV" + String(root.creature.level || 0)
                pixel: root.unit
                color: Util.alpha(Color.foreground, 0.85)
            }
        }

        BattleTypeChip {
            typeName: String(root.creature.type || "")
            unit: root.unit
            tint: root.tint
        }

        Row {
            width: parent.width
            spacing: root.unit * 3

            PixelText {
                text: "HP"
                pixel: root.unit
                color: Util.alpha(Color.foreground, 0.75)
                anchors.verticalCenter: parent.verticalCenter
            }

            Rectangle {
                id: track

                width: parent.width - root.unit * 9
                height: root.unit * 4
                anchors.verticalCenter: parent.verticalCenter
                color: Util.alpha(Color.foreground, 0.16)
                border.width: Math.max(1, Math.round(root.frameWidth / 2))
                border.color: Util.alpha(Color.foreground, 0.55)

                Rectangle {
                    x: track.border.width
                    y: track.border.width
                    height: parent.height - track.border.width * 2
                    width: (parent.width - track.border.width * 2) * root.fraction
                    color: root.fraction > 0.5 ? "#55b364"
                         : root.fraction > 0.2 ? "#d2a03c" : "#cc4b4b"

                    Behavior on width {
                        NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
                    }
                    Behavior on color { ColorAnimation { duration: 260 } }
                }
            }
        }

        PixelText {
            visible: root.showNumbers
            text: String(root.hp) + "/" + String(root.maxHp)
            pixel: root.unit
            color: Util.alpha(Color.foreground, 0.85)
            anchors.right: parent.right
        }
    }
}
