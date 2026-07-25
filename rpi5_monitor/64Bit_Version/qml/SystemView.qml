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

    // "bodies"-Grafik der aktiven Gruppe, falls vorhanden (Feldansicht mit
    // 2 Objekten). In diesem Modus ersetzt die Feldansicht die normale
    // Bild+Overlay / Grafik-Flow-Aufteilung komplett (analog zur alten
    // TwoBodiesWidget-Logik in tab_visuals.py).
    readonly property var bodiesGraphic: {
        var g = root.visuals.activeGroup.graphics
        for (var i = 0; i < g.length; i++) {
            if (g[i].type === "bodies") return g[i]
        }
        return null
    }

    function _chan(idx, fallback) {
        return (idx >= 0 && idx < root.values.length) ? root.values[idx] : fallback
    }

    function _bodyState(b) {
        return {
            label: b.label,
            color: b.color,
            diameter: root._chan(b.channelDiameter, b.diameter),
            x: root._chan(b.channelX, 0),
            y: root._chan(b.channelY, 0),
            angleDeg: root._chan(b.channelAngle, 0)
        }
    }

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

        // ── Feldansicht mit 2 Objekten (Position/Größe/Drehung) ───────────
        BodiesField {
            width: parent.width
            height: parent.height - Theme.touchTargetMin - Theme.spacingS
            visible: root.bodiesGraphic !== null
            label: root.bodiesGraphic ? root.bodiesGraphic.label : ""
            imageUrl: root.visuals.activeGroup.imageUrl
            fieldWidth: root.bodiesGraphic ? root.bodiesGraphic.fieldWidth : 2.0
            fieldHeight: root.bodiesGraphic ? root.bodiesGraphic.fieldHeight : 1.5
            readonly property var _emptyBody: ({ label: "", color: "#4ec9b0", diameter: 0.3, x: 0, y: 0, angleDeg: 0 })
            body1: root.bodiesGraphic ? root._bodyState(root.bodiesGraphic.body1) : _emptyBody
            body2: root.bodiesGraphic ? root._bodyState(root.bodiesGraphic.body2) : _emptyBody
        }

        Row {
            width: parent.width
            height: parent.height - Theme.touchTargetMin - Theme.spacingS
            spacing: Theme.spacingM
            visible: root.bodiesGraphic === null

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
                    delegate: Item {
                        id: ovDelegate
                        required property var modelData
                        readonly property real imgX: bgImage.x + (bgImage.width - bgImage.paintedWidth) / 2
                        readonly property real imgY: bgImage.y + (bgImage.height - bgImage.paintedHeight) / 2
                        readonly property string ovText: modelData.label + ": " +
                              (modelData.channel < root.values.length
                                   ? root.values[modelData.channel].toFixed(2) : "—")
                        x: imgX + bgImage.paintedWidth * modelData.xPct / 100
                        y: imgY + bgImage.paintedHeight * modelData.yPct / 100
                        width: ovLabel.implicitWidth + 12
                        height: ovLabel.implicitHeight + 6

                        // Schwarz hinterlegter Hintergrund, damit der Text
                        // auf jedem Bild lesbar bleibt (statt reinem
                        // Textumriss zuvor).
                        Rectangle {
                            anchors.fill: parent
                            color: "#0a0a0f"
                            opacity: 0.85
                            radius: 3
                            border.color: Qt.darker(modelData.color, 1.4)
                            border.width: 1
                        }
                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: 3
                            color: modelData.color
                        }

                        Text {
                            id: ovLabel
                            anchors.centerIn: parent
                            text: ovDelegate.ovText
                            color: modelData.color
                            font.pixelSize: 13
                            font.bold: true
                        }
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
                            active: modelData.type !== "bodies"
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
                                    value: modelData.channel < root.values.length
                                           ? root.values[modelData.channel] : 0
                                    maxVal: modelData.maxVal
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
