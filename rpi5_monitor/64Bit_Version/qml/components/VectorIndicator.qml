import QtQuick
import App

// Ersetzt die "vector"-Grafik (Richtung+Geschwindigkeit, z.B. Bewegungs-
// oder Windrichtung) aus tab_visuals.py — Pfeillänge skaliert mit
// speed/maxVal, Richtung über `rotation`.
Item {
    id: root
    implicitWidth: 110
    implicitHeight: 130

    property string label: ""
    property real angleDeg: 0
    property real speed: 0
    property real maxVal: 1

    readonly property real _len: Math.max(6, Math.min(1, speed / (maxVal || 1)) * 42)

    Item {
        id: field
        width: 96; height: 96
        anchors.horizontalCenter: parent.horizontalCenter

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: Theme.bg
            border.color: Theme.border
            border.width: 2
        }

        Item {
            anchors.centerIn: parent
            rotation: root.angleDeg
            Behavior on rotation { RotationAnimation { duration: 150; direction: RotationAnimation.Shortest } }

            Rectangle {
                width: 3
                height: root._len
                radius: 1.5
                color: Theme.accentBlue
                anchors.horizontalCenter: parent.horizontalCenter
                y: -root._len
            }
            // Pfeilspitze
            Rectangle {
                width: 10; height: 10
                rotation: 45
                color: Theme.accentBlue
                anchors.horizontalCenter: parent.horizontalCenter
                y: -root._len - 5
            }
        }

        Rectangle {
            width: 6; height: 6; radius: 3
            anchors.centerIn: parent
            color: Theme.accentBlue
        }
    }

    Column {
        anchors.top: field.bottom
        anchors.topMargin: 4
        anchors.horizontalCenter: parent.horizontalCenter
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.speed.toFixed(2)
            color: Theme.accentBlue
            font.family: Theme.fontMono
            font.pixelSize: Theme.fontSizeSmall
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
