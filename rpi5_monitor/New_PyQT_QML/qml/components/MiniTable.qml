import QtQuick
import App

// Ersetzt die "table"-Grafik aus tab_visuals.py (QTableWidget-Mini-
// Ansicht einer Kanal-Auswahl) durch ein einfaches Grid aus Text-Paaren.
Item {
    id: root
    implicitWidth: 190
    implicitHeight: 24 + Math.ceil(channels.length / 2) * 22

    property string title: ""
    property var channels: []      // Liste von Kanal-Indizes
    property var values: []        // appBridge.telemetry.latestValues

    Column {
        anchors.fill: parent
        spacing: 2

        Text {
            text: root.title
            color: Theme.accentBlue
            font.bold: true
            font.pixelSize: Theme.fontSizeSmall
        }

        Grid {
            columns: 2
            columnSpacing: 10
            rowSpacing: 1
            Repeater {
                model: root.channels
                delegate: Text {
                    required property int modelData
                    text: "Var_" + String(modelData).padStart(3, "0") + ": " +
                          (modelData < root.values.length ? root.values[modelData].toFixed(2) : "—")
                    color: Theme.text
                    font.family: Theme.fontMono
                    font.pixelSize: 11
                }
            }
        }
    }
}
