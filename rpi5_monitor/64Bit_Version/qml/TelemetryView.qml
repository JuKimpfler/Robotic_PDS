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

    // Min/Max/Delta sind leer, solange ein Kanal noch keinen endlichen Wert
    // hatte (TelemetryTableModel gibt dann None zurueck). In QML kommt das als
    // `undefined` an, NICHT als `null` — die fruehere Abfrage `!== null` war
    // deshalb immer wahr und lief in `undefined.toFixed()`. Ergebnis: bei jedem
    // ungenutzten Kanal blieben die drei Spalten leer statt "—" zu zeigen.
    function fmt(v, digits) {
        return (typeof v === "number" && isFinite(v)) ? v.toFixed(digits) : "—"
    }

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
                placeholderText: "Filter (Name oder Kanalnummer)…"
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
                required property string unit
                required property int channel

                implicitWidth: table.width
                implicitHeight: Math.round(40 * Theme.fontScale)
                color: Theme.bg
                radius: Theme.radiusS
                border.color: Theme.border
                border.width: 2

                Row {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 24

                    Text {
                        text: channel
                        color: Theme.textDim
                        font.family: Theme.fontMono
                        width: 34
                        horizontalAlignment: Text.AlignRight
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: varName
                        color: Theme.textjulius
                        font.family: Theme.fontMono
                        width: 160
                        elide: Text.ElideRight
                        font.pixelSize: Theme.fontSizeBase
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    // Wert und Einheit bewusst getrennt: so bleiben die Zahlen
                    // linksbuendig untereinander, auch wenn nur ein Teil der
                    // Kanaele eine Einheit hat.
                    Text {
                        text: current.toFixed(4)
                        color: valueColor
                        font.family: Theme.fontMono
                        font.bold: true
                        width: 90
                        horizontalAlignment: Text.AlignRight
                        font.pixelSize: Theme.fontSizeBase
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: unit
                        color: Theme.textDim
                        font.family: Theme.fontMono
                        width: 38
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "min " + root.fmt(minVal, 3)
                        color: Theme.textDim
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "max " + root.fmt(maxVal, 3)
                        color: Theme.textDim
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: "Δ " + root.fmt(delta, 3)
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
