import QtQuick
import QtQuick.Controls
import App
import "components"

// Migrationsplan Abschnitt 4.3. TableView statt QTableView, gespeist vom
// TelemetryTableModel. Der Suchfilter wird im MODELL ausgewertet
// (telemetry.setFilter) und nicht über `visible: false` im Delegate — eine
// TableView reserviert die Höhe unsichtbarer Zeilen weiterhin, die gefilterte
// Liste bestand vorher deshalb überwiegend aus Lücken.
Item {
    id: root
    property var telemetry: appBridge.telemetry

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS

        Row {
            id: toolbar
            width: parent.width
            spacing: Theme.spacingS

            TextField {
                id: filterField
                width: parent.width - resetBtn.width - Theme.spacingS
                height: Theme.touchTargetMin
                placeholderText: "Filter (Variablenname)…"
                color: Theme.text
                background: Rectangle {
                    color: Theme.bgInput
                    radius: Theme.radiusS
                    border.color: filterField.activeFocus ? Theme.highlight : Theme.border
                }
                // Entprellt: bei jedem Tastendruck das Modell zurückzusetzen
                // würde auf dem RPi sichtbar ruckeln.
                onTextChanged: filterDebounce.restart()
                Timer {
                    id: filterDebounce
                    interval: 150
                    onTriggered: root.telemetry.setFilter(filterField.text)
                }
            }

            AppButton {
                id: resetBtn
                text: "Min/Max zurücksetzen"
                onClicked: root.telemetry.clear_stats()
            }
        }

        Text {
            id: countLabel
            text: root.telemetry.visibleChannels === root.telemetry.activeChannels
                  ? "Aktive Kanäle: " + root.telemetry.activeChannels
                  : root.telemetry.visibleChannels + " von " +
                    root.telemetry.activeChannels + " Kanälen (gefiltert)"
            color: Theme.accentGreen
            font.pixelSize: Theme.fontSizeSmall
        }

        TableView {
            id: table
            width: parent.width
            height: parent.height - toolbar.height - countLabel.height - Theme.spacingS * 2
            clip: true
            model: telemetryModel
            columnSpacing: 1
            rowSpacing: 1
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true

            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                required property string varName
                required property real current
                required property var minVal
                required property var maxVal
                required property var delta
                required property string valueColor

                implicitWidth: table.width
                implicitHeight: 40
                color: Theme.bg
                radius: Theme.radiusS
                border.color: Theme.border
                border.width: 2

                Row {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 60

                    Text {
                        text: varName
                        color: Theme.textjulius
                        font.family: Theme.fontMono
                        width: 160
                        elide: Text.ElideRight
                        font.pixelSize: Theme.fontSizeBase
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: current.toFixed(4)
                        color: valueColor
                        font.family: Theme.fontMono
                        font.bold: true
                        width: 90
                        font.pixelSize: Theme.fontSizeBase
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "min " + (minVal !== null ? minVal.toFixed(3) : "—")
                        color: Theme.textDim
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "max " + (maxVal !== null ? maxVal.toFixed(3) : "—")
                        color: Theme.textDim
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "Δ " + (delta !== null ? delta.toFixed(3) : "—")
                        color: Theme.textDim
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }
    }
}
