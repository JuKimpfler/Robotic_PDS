import QtQuick
import QtQuick.Controls
import App

// Fußzeile: Verbindungs-LED, Pakete/s, Firmware-Stand des aktiven Roboters
// und die letzte Statusmeldung.
Rectangle {
    id: root
    implicitHeight: Math.round(34 * Theme.fontScale)
    color: Theme.bgMid
    border.color: Theme.border

    property int pps: 0
    property string message: ""
    property bool anyNodeConnected: false
    property string firmware: ""
    property int alarmLevel: 0
    property real batteryValue: 0

    Row {
        anchors.fill: parent
        anchors.leftMargin: Theme.spacingM
        anchors.rightMargin: Theme.spacingM
        spacing: Theme.spacingM

        // ── Verbindungs-LED ──────────────────────────────────────────────
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 12; height: 12; radius: 6
            color: root.anyNodeConnected ? Theme.ledOn : Theme.ledOff
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            font.family: Theme.fontMono
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.textDim
            text: root.pps + " Pkt/s"
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: !root.anyNodeConnected
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.accentAmber
            text: "keine Telemetrie"
        }

        // ── Firmware-Stand des aktiven Roboters (E2) ─────────────────────
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.firmware.length > 0
            font.family: Theme.fontMono
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.accentBlue
            text: root.firmware
        }

        // ── Akku-Warnung (C3) ────────────────────────────────────────────
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.alarmLevel > 0
            font.pixelSize: Theme.fontSizeSmall
            font.bold: true
            color: root.alarmLevel >= 2 ? Theme.ledOff : Theme.accentAmber
            text: (root.alarmLevel >= 2 ? "⚠ AKKU KRITISCH " : "⚠ Akku schwach ")
                  + root.batteryValue.toFixed(2)
        }
    }

    // Meldungen rechtsbündig, damit sie die festen Anzeigen links nie
    // verschieben — und mit Elide, damit eine lange Meldung die Zeile nicht
    // sprengt.
    Text {
        anchors.right: parent.right
        anchors.rightMargin: Theme.spacingM
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, root.width * 0.5)
        elide: Text.ElideRight
        horizontalAlignment: Text.AlignRight
        font.pixelSize: Theme.fontSizeSmall
        color: Theme.textjulius
        text: root.message
    }
}
