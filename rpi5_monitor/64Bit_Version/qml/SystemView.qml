import QtQuick
import QtQuick.Controls
import App
import "components"

// Migrationsplan Abschnitt 4.5 — der größte QML-Gewinn: Statt manueller
// QPainter-Overlays + Resize-Handling (alte tab_visuals.py, ~1700 Zeilen)
// hier deklarativ über Image + Repeater + prozentuale Anchors. Die
// Overlay-Positionen skalieren automatisch mit `bgImage.paintedWidth/
// paintedHeight` mit — kein manueller Resize-Code mehr nötig.
//
// ── BEARBEITEN ────────────────────────────────────────────────────────────
// Dieselbe Ansicht ist auch der Editor: "✎ Bearbeiten" macht die Textfelder
// im Bild ziehbar und tauscht rechts die Grafiken gegen das Bedienfeld
// (OverlayEditor.qml). Bewusst KEIN eigener Dialog — man positioniert
// Beschriftungen auf einem Bild nur sinnvoll, wenn man dabei das Bild in
// Originalgröße und die echten Messwerte sieht.
//
// Ein Textraster (30 Werte aus einem Eintrag) wird beim Ziehen als GANZER
// Block verschoben: gezogen wird irgendeine Zelle, gemeint ist immer die
// linke obere Ecke. Das ist der Grund, warum moveOverlayBy() relativ und
// nicht absolut arbeitet.
Item {
    id: root
    property var visuals: appBridge.visuals
    property var values: appBridge.telemetry.latestValues

    readonly property bool editing: visuals.editing

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

    // ── Ziehen: Zustand für die laufende Geste ───────────────────────────
    //  Alle Zellen mit demselben rawIndex verschieben sich mit — nur so
    //  bewegt sich ein Textraster als Block statt als einzelne Zelle.
    property int  dragRaw: -1
    property real dragDx: 0
    property real dragDy: 0

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

        // ── Werkzeugleiste ────────────────────────────────────────────────
        Row {
            id: toolbar
            width: parent.width
            height: Theme.touchTargetMin
            spacing: Theme.spacingS

            Label {
                text: "Gruppe:"
                color: Theme.text
                anchors.verticalCenter: parent.verticalCenter
            }
            ComboBox {
                width: 260
                height: Theme.touchTargetMin
                model: root.visuals.groupNames
                currentIndex: root.visuals.activeIndex
                onActivated: (idx) => root.visuals.setActiveIndex(idx)
            }

            AppButton {
                width: 150
                height: parent.height
                text: root.editing ? "✔ Fertig" : "✎ Bearbeiten"
                checkable: true
                checked: root.editing
                onToggled: (value) => root.visuals.setEditing(value)
            }
            AppButton {
                width: 150
                height: parent.height
                visible: root.editing
                text: "⟲ Rückgängig"
                enabled: root.visuals.canUndo
                onClicked: root.visuals.undo()
            }
            AppButton {
                width: 150
                height: parent.height
                visible: root.editing
                text: root.visuals.dirty ? "💾 Speichern *" : "💾 Speichern"
                enabled: root.visuals.dirty
                onClicked: root.visuals.save()
            }
            AppButton {
                width: 150
                height: parent.height
                visible: root.editing
                text: "✕ Verwerfen"
                enabled: root.visuals.dirty
                onClicked: root.visuals.revert()
            }
            Label {
                anchors.verticalCenter: parent.verticalCenter
                visible: root.editing
                text: root.visuals.configSource
                color: Theme.textDim
                font.pixelSize: Theme.fontSizeSmall
                elide: Text.ElideLeft
                width: Math.max(0, toolbar.width - 260 - 4 * 150 - 60
                                   - 6 * Theme.spacingS)
            }
        }

        // ── Der Teensy meldet eine andere Anordnung ───────────────────────
        //  Kommt nur, wenn hier von Hand bearbeitet wurde. Ohne diese Frage
        //  wäre die eigene Anordnung beim nächsten Flashen kommentarlos weg
        //  (siehe visuals_bridge.py, "_locally_edited").
        Rectangle {
            width: parent.width
            height: visible ? Theme.touchTargetMin + Theme.spacingS : 0
            visible: root.visuals.teensyUpdatePending
            color: Theme.warnBg
            radius: Theme.radiusS

            Row {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: Theme.spacingS
                spacing: Theme.spacingS

                Label {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Der Teensy meldet eine neue Anordnung."
                    color: Theme.accentAmber
                    font.pixelSize: Theme.fontSizeBase
                    font.bold: true
                }
                AppButton {
                    width: 200
                    height: Theme.touchTargetMin
                    text: "Teensy übernehmen"
                    onClicked: root.visuals.applyPendingTeensyConfig()
                }
                AppButton {
                    width: 200
                    height: Theme.touchTargetMin
                    text: "Eigene behalten"
                    onClicked: root.visuals.dismissPendingTeensyConfig()
                }
            }
        }

        Row {
            id: mainRow
            width: parent.width
            height: parent.height - toolbar.height - Theme.spacingS
                    - (root.visuals.teensyUpdatePending
                       ? Theme.touchTargetMin + Theme.spacingS + Theme.spacingS : 0)
            spacing: Theme.spacingM

            // ── Links: Vorschau (Bild mit Overlays oder Feldansicht) ─────
            Item {
                id: leftPane
                height: parent.height
                width: root.editing
                       ? parent.width * 0.56
                       : (root.bodiesGraphic !== null ? parent.width
                                                      : parent.width * 0.62)

                // ── Feldansicht mit 2 Objekten (Position/Größe/Drehung) ──
                BodiesField {
                    anchors.fill: parent
                    visible: root.bodiesGraphic !== null
                    label: root.bodiesGraphic ? root.bodiesGraphic.label : ""
                    // Das Gruppenbild ist in aller Regel eine Platinen-
                    // aufnahme; hinter einem Spielfeld ergibt das kein Bild,
                    // sondern Unruhe. Nur auf ausdrueckliche Ansage.
                    imageUrl: (root.bodiesGraphic && root.bodiesGraphic.showImage)
                              ? root.visuals.activeGroup.imageUrl : ""
                    // Feldmasse in ZENTIMETERN (x = Ost, y = Nord). Die
                    // Darstellung dreht das Feld um 90 Grad nach Osten —
                    // siehe BodiesField.qml.
                    fieldXCm: root.bodiesGraphic ? root.bodiesGraphic.fieldXCm : 180
                    fieldYCm: root.bodiesGraphic ? root.bodiesGraphic.fieldYCm : 240
                    goalWidthCm: root.bodiesGraphic ? root.bodiesGraphic.goalWidthCm : 45
                    goalDepthCm: root.bodiesGraphic ? root.bodiesGraphic.goalDepthCm : 10
                    readonly property var _emptyBody: ({ label: "", color: "#4ec9b0", diameter: 7, x: 0, y: 0, angleDeg: 0 })
                    body1: root.bodiesGraphic ? root._bodyState(root.bodiesGraphic.body1) : _emptyBody
                    body2: root.bodiesGraphic ? root._bodyState(root.bodiesGraphic.body2) : _emptyBody
                }

                // ── Bild mit Text-Overlays ───────────────────────────────
                Item {
                    id: imageArea
                    anchors.fill: parent
                    visible: root.bodiesGraphic === null

                    Image {
                        id: bgImage
                        anchors.fill: parent
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        source: root.visuals.activeGroup.imageUrl

                        // Daneben tippen hebt die Auswahl auf. Bewusst HIER
                        // und nicht am umschliessenden Item: als Vorfahre der
                        // Textfelder koennte dieser Handler auf denselben
                        // Tipper mitreagieren und die eben getroffene Auswahl
                        // sofort wieder loeschen. Als Geschwister UNTER den
                        // Feldern bekommt das Bild den Tipper nur, wenn
                        // tatsaechlich daneben getippt wurde.
                        TapHandler {
                            enabled: root.editing
                            onTapped: root.visuals.clearSelection()
                        }
                    }

                    Repeater {
                        model: root.visuals.activeGroup.overlays
                        delegate: Item {
                            id: ovDelegate
                            required property var modelData
                            readonly property real imgX: bgImage.x + (bgImage.width - bgImage.paintedWidth) / 2
                            readonly property real imgY: bgImage.y + (bgImage.height - bgImage.paintedHeight) / 2
                            // _has fängt auch negative Kanalnummern ab: bei einem
                            // channel_idx von -1 lief values[-1] auf undefined und
                            // .toFixed() warf einen TypeError, der das komplette
                            // Binding (und damit das Overlay) stillgelegt hat.
                            readonly property bool _has: modelData.channel >= 0 &&
                                                         modelData.channel < root.values.length
                            readonly property string ovText: modelData.label + ": " +
                                  (_has ? root.values[modelData.channel].toFixed(2) : "—")
                            readonly property bool selected:
                                root.editing &&
                                root.visuals.selectedList === "overlays" &&
                                root.visuals.selectedIndex === modelData.rawIndex
                            // Während der Geste laufen ALLE Zellen desselben
                            // Roheintrags mit — sonst löst sich ein Textraster
                            // beim Ziehen in Einzelteile auf.
                            readonly property real _dx: root.dragRaw === modelData.rawIndex ? root.dragDx : 0
                            readonly property real _dy: root.dragRaw === modelData.rawIndex ? root.dragDy : 0

                            x: imgX + bgImage.paintedWidth * modelData.xPct / 100 + _dx
                            y: imgY + bgImage.paintedHeight * modelData.yPct / 100 + _dy
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
                                border.color: ovDelegate.selected
                                              ? Theme.highlight
                                              : Qt.darker(ovDelegate.modelData.color, 1.4)
                                border.width: ovDelegate.selected ? 2 : 1
                            }
                            Rectangle {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                width: 3
                                color: ovDelegate.modelData.color
                            }

                            Text {
                                id: ovLabel
                                anchors.centerIn: parent
                                text: ovDelegate.ovText
                                color: ovDelegate.modelData.color
                                font.pixelSize: 13
                                font.bold: true
                            }

                            // Griff-Fläche: im Bearbeiten-Modus etwas größer
                            // als der Text, sonst trifft man ein 20 px hohes
                            // Kästchen mit dem Finger nicht.
                            Item {
                                anchors.centerIn: parent
                                width: parent.width + (root.editing ? 16 : 0)
                                height: parent.height + (root.editing ? 16 : 0)

                                TapHandler {
                                    enabled: root.editing
                                    onTapped: root.visuals.selectOverlayByRawIndex(
                                        ovDelegate.modelData.rawIndex)
                                }

                                DragHandler {
                                    enabled: root.editing
                                    // target: null -> der Handler bewegt nichts
                                    // selbst; die Verschiebung geht durch
                                    // root.dragDx/Dy an alle Zellen des Blocks.
                                    target: null
                                    onActiveChanged: {
                                        if (active) {
                                            root.visuals.selectOverlayByRawIndex(
                                                ovDelegate.modelData.rawIndex)
                                            root.dragRaw = ovDelegate.modelData.rawIndex
                                            UiState.pushLock()
                                        } else {
                                            UiState.popLock()
                                            var dx = root.dragDx
                                            var dy = root.dragDy
                                            var ri = ovDelegate.modelData.rawIndex
                                            // Erst zurücksetzen, dann melden:
                                            // sonst stünde die Verschiebung für
                                            // einen Bildaufbau doppelt drin.
                                            root.dragRaw = -1
                                            root.dragDx = 0
                                            root.dragDy = 0
                                            if (bgImage.paintedWidth > 0 && bgImage.paintedHeight > 0) {
                                                root.visuals.moveOverlayBy(
                                                    ri,
                                                    dx / bgImage.paintedWidth * 100,
                                                    dy / bgImage.paintedHeight * 100)
                                            }
                                        }
                                    }
                                    onActiveTranslationChanged: {
                                        root.dragDx = activeTranslation.x
                                        root.dragDy = activeTranslation.y
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ── Rechts (Normalbetrieb): konfigurierbare Grafiken ──────────
            Flickable {
                visible: !root.editing && root.bodiesGraphic === null
                width: visible ? parent.width * 0.38 - Theme.spacingM : 0
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
                                    value: root._chan(modelData.channel, 0)
                                }
                            }
                            Component {
                                id: rotationComp
                                RotationIndicator {
                                    label: modelData.label
                                    value: root._chan(modelData.channel, 0)
                                    maxVal: modelData.maxVal
                                }
                            }
                            Component {
                                id: vectorComp
                                VectorIndicator {
                                    label: modelData.label
                                    angleDeg: root._chan(modelData.channelAngle, 0)
                                    speed: root._chan(modelData.channelSpeed, 0)
                                    maxVal: modelData.maxVal
                                }
                            }
                            Component {
                                id: tableComp
                                MiniTable {
                                    title: modelData.title
                                    channels: modelData.channels
                                    channelNames: modelData.channelNames
                                    values: root.values
                                }
                            }
                        }
                    }
                }
            }

            // ── Rechts (Bearbeiten): das Bedienfeld ──────────────────────
            OverlayEditor {
                visible: root.editing
                width: visible ? parent.width * 0.44 - Theme.spacingM : 0
                height: parent.height
                visuals: root.visuals
                onPickChannelRequested: (key, current, allowNone) => {
                    chanPicker.targetKey = key
                    chanPicker.current = current
                    chanPicker.allowNone = allowNone
                    chanPicker.open()
                }
            }
        }
    }

    ChannelPicker {
        id: chanPicker
        property string targetKey: ""
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        channelNames: root.visuals.channelNames
        onPicked: (channel) => root.visuals.setField(chanPicker.targetKey, channel)
    }
}
