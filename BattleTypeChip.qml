// A creature's type, as a coloured tag. Part of the battle screen
// (Battle.qml); see docs/BATTLES.md.
//
// The colour is a deliberate accent rather than a theme token: a type is the
// creature's identity, and it has to mean the same thing on every theme and
// in both light and dark. The label is always drawn dark, because every tint
// in the set is a mid tone chosen to take dark text.

import QtQuick

Item {
    id: root

    property string typeName: ""
    property int unit: 3
    property color tint: "#5f9ea0"

    implicitWidth: plate.width
    implicitHeight: plate.height

    Rectangle {
        id: plate

        width: label.implicitWidth + root.unit * 5
        height: label.implicitHeight + root.unit * 4
        color: root.tint

        PixelText {
            id: label
            anchors.centerIn: parent
            text: root.typeName
            pixel: Math.max(2, root.unit - 1)
            color: "#101010"
            shadowColor: "transparent"
        }
    }
}
