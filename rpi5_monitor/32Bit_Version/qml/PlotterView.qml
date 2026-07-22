import QtQuick 2.15
import QtQuick.Controls 2.15
import App 1.0
import "components"

// Migrationsplan Abschnitt 4.4 — Option C: eigenes QQuickPaintedItem
// (PlotCanvas, siehe bridge/plot_bridge.py) statt PyQtGraph.
// Touch-Bedienung: PinchHandler fürs Zoomen der Punktezahl, DragHandler
// nicht nötig, da Freeze bereits den Snapshot fixiert.
Item {
    id: root
    property var plotter: appBridge.plotter

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS

        Row {
            width: parent.width
            spacing: Theme.spacingS

            Label { text: "Variable:"; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }

            ComboBox {
                id: varCombo
                width: 240
                height: Theme.touchTargetMin
                model: plotter.variableNames
                currentIndex: plotter.selectedVar
                onActivated: (idx) => plotter.setSelectedVar(idx)
            }

            Label { text: "Punkte:"; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }

            SpinBox {
                id: ptsSpin
                height: Theme.touchTargetMin
                from: 50; to: 600; stepSize: 50
                value: plotter.pointsCount
                onValueModified: plotter.setPointsCount(value)
            }

            AppButton {
                id: freezeBtn
                text: plotter.frozen ? "Weiter" : "Einfrieren"
                checkable: true
                checked: plotter.frozen
                onClicked: plotter.setFrozen(checked)
            }

            AppButton {
                text: "Löschen"
                onClicked: plotter.clearBuffer()
            }
        }

        Item {
            id: plotArea
            width: parent.width
            height: parent.height - 120

            PlotCanvas {
                id: canvas
                anchors.fill: parent
                plotBridge: root.plotter
            }

            // Touch: Pinch verändert die sichtbare Punktezahl (= Zoom)
            PinchHandler {
                id: pinch
                target: null
                onActiveChanged: {
                    if (!active) return
                    var n = Math.round(plotter.pointsCount / pinch.scale)
                    plotter.setPointsCount(Math.max(50, Math.min(600, n)))
                }
            }

            Rectangle {
                visible: plotter.frozen
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.margins: Theme.spacingS
                radius: Theme.radiusS
                color: "#3a2f00"
                width: frozenLbl.width + 16
                height: frozenLbl.height + 10
                Text {
                    id: frozenLbl
                    anchors.centerIn: parent
                    text: "EINGEFROREN — Live-Queue läuft weiter."
                    color: Theme.accentAmber
                    font.bold: true
                }
            }
        }

        Text {
            text: plotter.statsText
            color: Theme.textDim
            font.family: Theme.fontMono
        }
    }
}
