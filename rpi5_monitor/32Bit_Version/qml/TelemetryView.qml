import QtQuick 2.15
import QtQuick.Controls 2.15
import App 1.0
import "components"

// Migrationsplan Abschnitt 4.3. TableView statt QTableView, gespeist
// vom (kaum geänderten) TelemetryTableModel — inkl. Suchfeld, das im
// Original nicht vorhanden war (hier via QSortFilterProxyModel-freie,
// simple JS-Filterung auf sichtbarer Ebene ergänzt).
Item {
    id: root

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS

        Row {
            width: parent.width
            spacing: Theme.spacingS

            TextField {
                id: filterField
                width: parent.width - resetBtn.width - Theme.spacingS
                placeholderText: "Filter (Variablenname)…"
                color: Theme.text
                background: Rectangle {
                    color: Theme.bgInput
                    radius: Theme.radiusS
                    border.color: filterField.activeFocus ? Theme.highlight : Theme.border
                }
            }

            AppButton {
                id: resetBtn
                text: "Min/Max zurücksetzen"
                onClicked: telemetryModel.clear_stats()
            }
        }

        Text {
            text: "Aktive Kanäle: " + telemetryModel.rowCount()
            color: Theme.accentGreen
            font.pixelSize: Theme.fontSizeSmall
        }

        TableView {
            id: table
            width: parent.width
            height: parent.height - filterField.height - 40 - Theme.spacingS * 2
            clip: true
            model: telemetryModel
            columnSpacing: 1
            rowSpacing: 1
            boundsBehavior: Flickable.StopAtBounds

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
                visible: filterField.text.length === 0 ||
                         varName.toLowerCase().indexOf(filterField.text.toLowerCase()) !== -1
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
                        width: 120
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
