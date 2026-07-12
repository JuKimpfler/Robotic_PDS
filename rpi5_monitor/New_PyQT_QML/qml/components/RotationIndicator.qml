import QtQuick
import App

// Ersetzt die "rotation"-Grafik aus tab_visuals.py: ein Zeiger, der sich
// um den Kanalwert (Grad) dreht — in QML "kostenlos" über die eingebaute
// `rotation`-Property statt manueller QPainter-Transform-Matrizen.
Item {
    id: root
    implicitWidth: 96
    implicitHeight: 116

    property string label: ""
    property real angleDeg: 0

    Rectangle {
        id: dial
        width: 76; height: 76; radius: 38
        anchors.horizontalCenter: parent.horizontalCenter
        color: Theme.bg
        border.color: Theme.border
        border.width: 2

        Rectangle {
            width: 4; height: 30
            radius: 2
            color: Theme.accentAmber
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            transformOrigin: Item.Bottom
            y: parent.height / 2 - height
            rotation: root.angleDeg

            Behavior on rotation { RotationAnimation { duration: 120; direction: RotationAnimation.Shortest } }
        }

        Rectangle {
            width: 8; height: 8; radius: 4
            anchors.centerIn: parent
            color: Theme.accentAmber
        }
    }

    Column {
        anchors.top: dial.bottom
        anchors.topMargin: 4
        anchors.horizontalCenter: parent.horizontalCenter
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.angleDeg.toFixed(0) + "°"
            color: Theme.accentAmber
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
