import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "components"

// Live-Plotter mit bis zu acht Kurven, Oszilloskop-Trigger und
// Ereignismarken. Gezeichnet wird von PlotCanvas (QQuickPaintedItem,
// siehe bridge/plot_bridge.py) — hier steht nur die Bedienung.
Item {
    id: root
    property var plotter: appBridge.plotter

    // Kanalauswahl als eigenes Fenster: bei 200 Kanälen ist eine Liste mit
    // Suchfeld deutlich brauchbarer als eine ComboBox, und der Plot bleibt
    // beim Auswählen sichtbar.
    Popup {
        id: channelPicker
        modal: true
        focus: true
        width: Math.min(root.width * 0.7, 560)
        height: Math.min(root.height * 0.8, 620)
        anchors.centerIn: Overlay.overlay
        padding: Theme.spacingM
        background: Rectangle {
            color: Theme.bgMid
            border.color: Theme.border
            radius: Theme.radiusM
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.spacingS

            Text {
                text: "Kurven wählen (max. " + root.plotter.maxCurves + ")"
                color: Theme.text
                font.bold: true
                font.pixelSize: Theme.fontSizeLarge
            }

            TextField {
                id: pickerSearch
                Layout.fillWidth: true
                placeholderText: "Kanal suchen …"
                inputMethodHints: Qt.ImhNoPredictiveText
            }

            ListView {
                id: pickerList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                reuseItems: true
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                // Die Filterung passiert in JavaScript über die Namensliste;
                // sie läuft nur beim Tippen, nicht im Datentakt.
                model: {
                    var names = root.plotter.variableNames
                    var q = pickerSearch.text.trim().toLowerCase()
                    var out = []
                    for (var i = 0; i < names.length; ++i) {
                        if (q.length === 0 || names[i].toLowerCase().indexOf(q) >= 0
                                || String(i) === q)
                            out.push({ idx: i, name: names[i] })
                    }
                    return out
                }

                delegate: ItemDelegate {
                    required property var modelData
                    width: pickerList.width
                    height: Theme.touchTargetMin
                    highlighted: root.plotter.channels.indexOf(modelData.idx) >= 0
                    onClicked: root.plotter.toggleChannel(modelData.idx)

                    contentItem: Row {
                        spacing: Theme.spacingS
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 14; height: 14; radius: 3
                            border.color: Theme.border
                            border.width: 1
                            color: {
                                var pos = root.plotter.channels.indexOf(modelData.idx)
                                return pos >= 0 ? root.plotter.curveColors[pos] : "transparent"
                            }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.idx + "  " + modelData.name
                            color: Theme.text
                            font.family: Theme.fontMono
                            font.pixelSize: Theme.fontSizeBase
                        }
                    }
                }
            }

            AppButton {
                Layout.fillWidth: true
                text: "Schließen"
                onClicked: channelPicker.close()
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS

        // ── Werkzeugleiste ───────────────────────────────────────────────
        Flow {
            Layout.fillWidth: true
            spacing: Theme.spacingS

            AppButton {
                text: "Kurven (" + root.plotter.channels.length + ") …"
                onClicked: channelPicker.open()
            }

            Row {
                spacing: Theme.spacingXs
                Label {
                    text: "Punkte:"
                    color: Theme.text
                    anchors.verticalCenter: parent.verticalCenter
                }
                SpinBox {
                    // Grenzen aus settings.json -> "ranges.plotPoints"
                    // (siehe app_settings.py). PlotBridge begrenzt auf
                    // denselben Bereich, zusaetzlich auf die tatsaechliche
                    // Groesse des Ringpuffers.
                    readonly property var rng: appBridge.settings.ranges.plotPoints
                    height: Theme.touchTargetMin
                    from: rng.min; to: rng.max; stepSize: rng.step
                    value: root.plotter.pointsCount
                    onValueModified: root.plotter.setPointsCount(value)
                }
            }

            AppSwitch {
                text: "Gemeinsame Skala"
                checked: root.plotter.sharedScale
                onToggled: (v) => root.plotter.setSharedScale(v)
            }

            AppButton {
                text: root.plotter.frozen ? "Weiter" : "Einfrieren"
                checkable: true
                checked: root.plotter.frozen
                onToggled: (v) => root.plotter.setFrozen(v)
            }

            AppButton {
                text: "Löschen"
                onClicked: root.plotter.clearBuffer()
            }
        }

        // ── Trigger (A3) ─────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: triggerRow.implicitHeight + Theme.spacingS * 2
            radius: Theme.radiusM
            color: Theme.bgMid
            border.color: root.plotter.triggerEnabled ? Theme.accentAmber : Theme.border

            // NICHT `anchors.fill: parent`: die Hoehe des Kastens kommt aus
            // triggerRow.implicitHeight, und anchors.fill wuerde die Hoehe der
            // Flow zurueck an den Kasten binden — eine Schleife. Qt loest sie
            // auf, indem es eine Seite fallen laesst, und der Kasten fiel dann
            // beim Einschalten des Triggers von 192 auf 16 Pixel zusammen:
            // Schwelle, Modus und Nachlauf waren nicht mehr erreichbar.
            // Nur die BREITE binden, die Hoehe rechnet die Flow selbst aus.
            Flow {
                id: triggerRow
                x: Theme.spacingS
                y: Theme.spacingS
                width: parent.width - 2 * Theme.spacingS
                spacing: Theme.spacingS

                AppSwitch {
                    text: "Trigger"
                    checked: root.plotter.triggerEnabled
                    onToggled: (v) => root.plotter.setTriggerEnabled(v)
                }

                ComboBox {
                    id: trigChannel
                    width: 200
                    height: Theme.touchTargetMin
                    enabled: root.plotter.triggerEnabled
                    model: root.plotter.variableNames
                    currentIndex: root.plotter.triggerChannel
                    onActivated: (idx) => root.plotter.setTriggerChannel(idx)
                }

                ComboBox {
                    id: trigMode
                    width: 210
                    height: Theme.touchTargetMin
                    enabled: root.plotter.triggerEnabled
                    textRole: "label"
                    valueRole: "value"
                    model: root.plotter.triggerModes
                    // indexOfValue braucht valueRole; beim ersten Aufbau ist
                    // das Modell schon da, deshalb genügt die Zuweisung hier.
                    currentIndex: indexOfValue(root.plotter.triggerMode)
                    onActivated: (idx) => root.plotter.setTriggerMode(valueAt(idx))
                }

                Row {
                    spacing: Theme.spacingXs
                    Label {
                        text: "Schwelle:"
                        color: Theme.text
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    TextField {
                        width: 110
                        height: Theme.touchTargetMin
                        enabled: root.plotter.triggerEnabled
                        text: root.plotter.triggerLevel.toFixed(3)
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        onEditingFinished: {
                            var v = parseFloat(text.replace(",", "."))
                            if (!isNaN(v)) root.plotter.setTriggerLevel(v)
                        }
                    }
                }

                Row {
                    spacing: Theme.spacingXs
                    visible: root.plotter.triggerMode === "change"
                             || root.plotter.triggerMode === "outside"
                    Label {
                        text: "Δ:"
                        color: Theme.text
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    TextField {
                        width: 90
                        height: Theme.touchTargetMin
                        enabled: root.plotter.triggerEnabled
                        text: root.plotter.triggerDelta.toFixed(3)
                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                        onEditingFinished: {
                            var v = parseFloat(text.replace(",", "."))
                            if (!isNaN(v)) root.plotter.setTriggerDelta(v)
                        }
                    }
                }

                Row {
                    spacing: Theme.spacingXs
                    Label {
                        text: "Nachlauf:"
                        color: Theme.text
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    SpinBox {
                        // settings.json -> "ranges.plotTriggerPost", dort als
                        // Anteil 0..1 notiert. Die SpinBox rechnet nur in
                        // ganzen Zahlen, deshalb ueberall x100 (= Prozent).
                        readonly property var rng: appBridge.settings.ranges.plotTriggerPost
                        height: Theme.touchTargetMin
                        from: Math.round(rng.min * 100)
                        to: Math.round(rng.max * 100)
                        stepSize: Math.max(1, Math.round(rng.step * 100))
                        enabled: root.plotter.triggerEnabled
                        value: Math.round(root.plotter.triggerPostFraction * 100)
                        textFromValue: (v) => v + " %"
                        onValueModified: root.plotter.setTriggerPostFraction(value / 100)
                    }
                }

                AppSwitch {
                    text: "nur markieren"
                    checked: root.plotter.triggerMarkOnly
                    onToggled: (v) => root.plotter.setTriggerMarkOnly(v)
                }

                AppButton {
                    text: "Neu scharf"
                    enabled: root.plotter.triggerEnabled && root.plotter.frozen
                    onClicked: root.plotter.rearmTrigger()
                }

                // Ein DIREKTES Kind einer Flow darf keine Anker haben — Qt
                // meldet "Cannot specify anchors for items inside Flow. Flow
                // will not function." und ordnet danach gar nichts mehr an.
                // Senkrecht zentriert wird deshalb ueber die Textausrichtung.
                Text {
                    height: Theme.touchTargetMin
                    verticalAlignment: Text.AlignVCenter
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSizeSmall
                    text: !root.plotter.triggerEnabled ? ""
                          : root.plotter.frozen
                            ? "ausgelöst (" + root.plotter.triggerCount + ")"
                            : root.plotter.triggerMarkOnly
                              ? "markiert: " + root.plotter.triggerCount
                              : "scharf, wartet … (" + root.plotter.triggerCount + ")"
                }
            }
        }

        // ── Plotfläche ───────────────────────────────────────────────────
        Item {
            id: plotArea
            Layout.fillWidth: true
            Layout.fillHeight: true

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
                    if (active) return
                    var n = Math.round(root.plotter.pointsCount / pinch.scale)
                    root.plotter.setPointsCount(Math.max(50, Math.min(600, n)))
                }
            }

            Rectangle {
                visible: root.plotter.frozen
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.margins: Theme.spacingS
                radius: Theme.radiusS
                color: Theme.warnBg
                width: frozenLbl.width + 16
                height: frozenLbl.height + 10
                Text {
                    id: frozenLbl
                    anchors.centerIn: parent
                    text: "EINGEFROREN — Aufzeichnung läuft weiter (gestrichelt)."
                    color: Theme.accentAmber
                    font.bold: true
                    font.pixelSize: Theme.fontSizeSmall
                }
            }
        }

        // ── Legende (A2) ─────────────────────────────────────────────────
        Flow {
            Layout.fillWidth: true
            spacing: Theme.spacingM

            Repeater {
                model: root.plotter.curveInfo
                delegate: Row {
                    required property var modelData
                    spacing: Theme.spacingXs
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 18; height: 4; radius: 2
                        color: modelData.color
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.text
                        text: modelData.name
                              + (modelData.unit.length ? " [" + modelData.unit + "]" : "")
                              + (modelData.valid
                                 ? "  " + modelData.last.toFixed(3)
                                   + "  (" + modelData.min.toFixed(2)
                                   + " … " + modelData.max.toFixed(2) + ")"
                                 : "  —")
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: root.plotter.statsText
            color: Theme.textDim
            font.family: Theme.fontMono
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideRight
        }
    }
}
