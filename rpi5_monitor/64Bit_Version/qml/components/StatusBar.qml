import QtQuick
import App

// Fußzeile: Paketrate, Verbindungszustand und die letzte Statusmeldung
// (appBridge.statusText — Node gewechselt, Kanalnamen angefordert,
// Empfänger neu gestartet, Teensy-Neustart erkannt ...).
Rectangle {
    id: root
    implicitHeight: 34
    color: Theme.bgMid
    border.color: Theme.border

    property int pps: 0
    property string message: ""
    property bool anyNodeConnected: false

    Row {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Theme.spacingM
        anchors.rightMargin: Theme.spacingM
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.spacingL

        Rectangle {
            width: 10; height: 10; radius: 5
            anchors.verticalCenter: parent.verticalCenter
            color: root.anyNodeConnected ? Theme.ledOn : Theme.ledOff
        }

        Text {
            text: root.pps + " Pakete/s"
            color: root.anyNodeConnected ? Theme.accentGreen : Theme.textDim
            font.family: Theme.fontMono
            font.pixelSize: Theme.fontSizeSmall
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.anyNodeConnected ? "" : "keine Telemetrie"
            visible: !root.anyNodeConnected
            color: Theme.accentAmber
            font.pixelSize: Theme.fontSizeSmall
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.message
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideRight
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, root.width - 400)
        }
    }
}
