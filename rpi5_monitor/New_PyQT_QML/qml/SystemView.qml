import QtQuick
import QtQuick.Controls
import App
import "components"

// Migrationsplan Abschnitt 4.5 — der größte QML-Gewinn: Statt manueller
// QPainter-Overlays + Resize-Handling (alte tab_visuals.py, ~1700 Zeilen)
// hier deklarativ über Image + Repeater + prozentuale Anchors. Die
// Overlay-Positionen skalieren automatisch mit `bgImage.paintedWidth/
// paintedHeight` mit — kein manueller Resize-Code mehr nötig.
Item {
    id: root
    property var visuals: appBridge.visuals
    property var values: appBridge.telemetry.latestValues

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS

        Row {
            width: parent.width
            spacing: Theme.spacingS
            Label { text: "Gruppe:"; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }
            ComboBox {
                width: 260
                height: Theme.touchTargetMin
                model: root.visuals.groupNames
                currentIndex: root.visuals.activeIndex
                onActivated: (idx) => root.visuals.setActiveIndex(idx)
            }
        }

        Row {
            width: parent.width
            height: parent.height - Theme.touchTargetMin - Theme.spacingS
            spacing: Theme.spacingM

            // ── Links: Bild mit Text-Overlays ────────────────────────────
            Item {
                id: imageArea
                width: parent.width * 0.62
                height: parent.height

                Image {
                    id: bgImage
                    anchors.fill: parent
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    source: root.visuals.activeGroup.imageUrl
                }

                Repeater {
                    model: root.visuals.activeGroup.overlays
                    delegate: Text {
                        required property var modelData
                        readonly property real imgX: bgImage.x + (bgImage.width - bgImage.paintedWidth) / 2
                        readonly property real imgY: bgImage.y + (bgImage.height - bgImage.paintedHeight) / 2
                        x: imgX + bgImage.paintedWidth * modelData.xPct / 100
                        y: imgY + bgImage.paintedHeight * modelData.yPct / 100
                        text: modelData.label + ": " +
                              (modelData.channel < root.values.length
                                   ? root.values[modelData.channel].toFixed(2) : "—")
                        color: modelData.color
                        font.pixelSize: 13
                        font.bold: true
                        style: Text.Outline
                        styleColor: "#000000"
                    }
                }
            }

            // ── Rechts: konfigurierbare Grafiken (Gauges/Rotation/Vektor/Tabelle) ──
            Flickable {
                width: parent.width * 0.38 - Theme.spacingM
                height: parent.height
                contentHeight: graphicsFlow.height
                clip: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Flow {
                    id: graphicsFlow
                    width: parent.width
                    spacing: Theme.spacingS

                    Repeater {
                        model: root.visuals.activeGroup.graphics
                        delegate: Loader {
                            required property var modelData
                            sourceComponent: {
                                switch (modelData.type) {
                                    case "gauge":    return gaugeComp
                                    case "rotation": return rotationComp
                                    case "vector":   return vectorComp
                                    case "table":    return tableComp
                                    default:         return null
                                }
                            }
                            Component {
                                id: gaugeComp
                                Gauge {
                                    label: modelData.label
                                    minVal: modelData.min
                                    maxVal: modelData.max
                                    value: modelData.channel < root.values.length
                                           ? root.values[modelData.channel] : 0
                                }
                            }
                            Component {
                                id: rotationComp
                                RotationIndicator {
                                    label: modelData.label
                                    angleDeg: modelData.channel < root.values.length
                                              ? root.values[modelData.channel] : 0
                                }
                            }
                            Component {
                                id: vectorComp
                                VectorIndicator {
                                    label: modelData.label
                                    angleDeg: modelData.channelAngle < root.values.length
                                              ? root.values[modelData.channelAngle] : 0
                                    speed: modelData.channelSpeed < root.values.length
                                           ? root.values[modelData.channelSpeed] : 0
                                    maxVal: modelData.maxVal
                                }
                            }
                            Component {
                                id: tableComp
                                MiniTable {
                                    title: modelData.title
                                    channels: modelData.channels
                                    values: root.values
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
