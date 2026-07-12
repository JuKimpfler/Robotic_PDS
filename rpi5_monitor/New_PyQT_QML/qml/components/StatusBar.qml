import QtQuick
import App

Rectangle {
    id: root
    implicitHeight: 34
    color: Theme.bgMid
    border.color: Theme.border

    property int pps: 0
    property string message: ""

    Row {
        anchors.left: parent.left
        anchors.leftMargin: Theme.spacingM
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.spacingL

        Text {
            text: "📡 " + root.pps + " Pakete/s"
            color: Theme.accentGreen
            font.family: Theme.fontMono
            font.pixelSize: Theme.fontSizeSmall
        }

        Text {
            text: root.message
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
