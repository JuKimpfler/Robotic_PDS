import QtQuick
import App

// Ersetzt die "table"-Grafik aus tab_visuals.py (QTableWidget-Mini-
// Ansicht einer Kanal-Auswahl). Jede Zelle bekommt jetzt eine eigene
// Karte mit Innenabstand statt eng gepackter, hintergrundloser
// Text-Paare -> deutlich weniger "gedrängt".
Item {
    id: root
    readonly property int _cols: channels.length > 12 ? 3 : 2
    readonly property int _cellW: 128
    readonly property int _cellH: 40
    implicitWidth: _cols * _cellW + (_cols - 1) * Theme.spacingXs + Theme.spacingS * 2
    implicitHeight: titleRow.height + Theme.spacingXs +
                     Math.ceil(channels.length / _cols) * (_cellH + Theme.spacingXs) +
                     Theme.spacingS * 2

    property string title: ""
    property var channels: []      // Liste von Kanal-Indizes
    property var values: []        // appBridge.telemetry.latestValues

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusM
        color: Theme.bgMid
        border.color: Theme.border
        border.width: 1
    }

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingXs

        Row {
            id: titleRow
            height: 20
            Text {
                text: root.title
                color: Theme.accentBlue
                font.bold: true
                font.pixelSize: Theme.fontSizeSmall
            }
        }

        Grid {
            columns: root._cols
            columnSpacing: Theme.spacingXs
            rowSpacing: Theme.spacingXs

            Repeater {
                model: root.channels
                delegate: Rectangle {
                    id: cell
                    required property int modelData
                    width: root._cellW
                    height: root._cellH
                    radius: Theme.radiusS
                    color: Theme.bg
                    border.color: Theme.border
                    border.width: 1

                    readonly property bool _has: modelData < root.values.length
                    readonly property real _val: _has ? root.values[modelData] : 0

                    Column {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 6
                        spacing: 1
                        Text {
                            text: "Var_" + String(cell.modelData).padStart(3, "0")
                            color: Theme.textDim
                            font.family: Theme.fontMono
                            font.pixelSize: 10
                        }
                        Text {
                            text: cell._has ? cell._val.toFixed(2) : "—"
                            color: Theme.accentGreen
                            font.family: Theme.fontMono
                            font.bold: true
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
}
