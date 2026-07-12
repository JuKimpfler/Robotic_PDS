import QtQuick
import QtQuick.Controls
import App
import "components"

// Migrationsplan Abschnitt 4.6. Baut die komplette Parameter-Oberfläche
// deklarativ aus appBridge.params.groups auf (siehe param_bridge.py::
// _build_groups) — kein Python-Widget-Factory-Code mehr nötig.
// Werte-Zustand lebt bewusst nur hier in QML (siehe Docstring in
// param_bridge.py); Python bekommt nur Change-Events zum Weitersenden.
Item {
    id: root
    property var params: appBridge.params

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS
        visible: params.configError.length === 0

        // ── Toolbar ────────────────────────────────────────────────────────
        Rectangle {
            width: parent.width
            height: 56
            radius: Theme.radiusM
            color: Theme.bgMid
            border.color: Theme.border

            Row {
                anchors.fill: parent
                anchors.margins: Theme.spacingS
                spacing: Theme.spacingM

                Text {
                    text: params.statusText
                    color: Theme.accentGreen
                    font.family: Theme.fontMono
                    font.pixelSize: Theme.fontSizeSmall
                    anchors.verticalCenter: parent.verticalCenter
                    width: 460
                    elide: Text.ElideRight
                }

                Switch {
                    text: "Übertragung aktiv"
                    checked: params.enabled
                    anchors.verticalCenter: parent.verticalCenter
                    onToggled: params.setEnabled(checked)
                }

                Button {
                    text: "💾 Als Default speichern"
                    height: Theme.touchTargetMin
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: params.saveDefaults()
                }
            }
        }

        // ── Gruppen-Auswahl ───────────────────────────────────────────────
        Row {
            width: parent.width
            spacing: Theme.spacingS
            Label { text: "Gruppe:"; color: Theme.accentBlue; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
            ComboBox {
                id: groupCombo
                width: 320
                height: Theme.touchTargetMin
                model: params.groups.map(g => g.title)
            }
        }

        // ── Aktive Gruppen-Seite ─────────────────────────────────────────
        Flickable {
            width: parent.width
            height: parent.height - 56 - Theme.touchTargetMin - Theme.spacingS * 3
            clip: true
            contentHeight: pageLoader.item ? pageLoader.item.implicitHeight : 0
            // Während der Joystick bedient wird, soll diese Seite nicht
            // gleichzeitig mitscrollen (siehe UiState.qml).
            interactive: !UiState.navigationLocked
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Loader {
                id: pageLoader
                width: parent.width
                property var groupData: params.groups.length > groupCombo.currentIndex
                                         ? params.groups[groupCombo.currentIndex] : null
                sourceComponent: groupPageComp
            }
        }
    }

    // ── Fehleranzeige, falls param_config.json ungültig ist ──────────────
    Rectangle {
        anchors.fill: parent
        anchors.margins: Theme.spacingM
        visible: params.configError.length > 0
        color: "#3a1f1f"
        radius: Theme.radiusM
        Text {
            anchors.fill: parent
            anchors.margins: Theme.spacingM
            wrapMode: Text.WordWrap
            color: "#e74c3c"
            font.family: Theme.fontMono
            text: "⚠ param_config.json ist ungültig — Parameter-Tab deaktiviert.\n\n" +
                  params.configError +
                  "\n\nBitte param_config.json korrigieren und die GUI neu starten."
        }
    }

    // ── Eine Gruppen-Seite: Floats/Bools/Joysticks nebeneinander ─────────
    Component {
        id: groupPageComp
        Column {
            id: pageCol
            spacing: Theme.spacingM

            property var g: pageLoader.groupData

            Row {
                width: pageCol.width
                spacing: Theme.spacingL
                visible: pageCol.g !== null

                // Links: Slider / Zahlen / Text / Bools
                Column {
                    id: leftCol
                    width: (pageCol.g && pageCol.g.joysticks.length > 0) ? pageCol.width * 0.62 : pageCol.width
                    spacing: Theme.spacingXs

                    Repeater {
                        model: pageCol.g ? pageCol.g.floats : []
                        delegate: Loader {
                            required property var modelData
                            width: leftCol.width
                            sourceComponent: {
                                switch (modelData.widget) {
                                    case "slider": return sliderComp
                                    case "number": return numberComp
                                    case "text":   return numberComp
                                    default:       return numberComp
                                }
                            }
                            Component {
                                id: sliderComp
                                TouchSlider {
                                    width: leftCol.width
                                    label: modelData.name
                                    from: modelData.min; to: modelData.max
                                    value: modelData.default
                                    onMoved: (v) => pageCol._sendFloat(modelData.index, v)
                                }
                            }
                            Component {
                                id: numberComp
                                Row {
                                    width: leftCol.width
                                    height: Theme.touchTargetMin
                                    spacing: Theme.spacingS
                                    Label {
                                        text: modelData.name
                                        width: 150
                                        color: Theme.text
                                        anchors.verticalCenter: parent.verticalCenter
                                        elide: Text.ElideRight
                                    }
                                    SpinBox {
                                        id: spin
                                        height: Theme.touchTargetMin
                                        width: 190
                                        // editable:true = Eingabe per (USB-)Tastatur möglich,
                                        // zusätzlich zu den +/- Tasten unten. Vorher fehlte
                                        // dieses Flag -> nur die Tasten funktionierten.
                                        editable: true
                                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                                        from: Math.round(modelData.min * 1000)
                                        to: Math.round(modelData.max * 1000)
                                        stepSize: Math.max(1, Math.round(modelData.step * 1000))
                                        value: Math.round(modelData.default * 1000)
                                        textFromValue: (v) => (v / 1000).toFixed(3)
                                        valueFromText: (t) => Math.round(parseFloat(t.replace(",", ".")) * 1000)
                                        onValueModified: pageCol._sendFloat(modelData.index, value / 1000)

                                        // Große, gut treffbare +/- Tasten für Touch, statt der
                                        // sehr kleinen Standard-Pfeilsymbole.
                                        up.indicator: Rectangle {
                                            x: spin.width - width
                                            height: spin.height
                                            width: Theme.touchTargetMin
                                            color: spin.up.pressed ? Theme.highlight : Theme.bgInput
                                            border.color: Theme.border
                                            Text {
                                                anchors.centerIn: parent
                                                text: "+"
                                                font.pixelSize: Theme.fontSizeLarge
                                                font.bold: true
                                                color: Theme.text
                                            }
                                        }
                                        down.indicator: Rectangle {
                                            x: 0
                                            height: spin.height
                                            width: Theme.touchTargetMin
                                            color: spin.down.pressed ? Theme.highlight : Theme.bgInput
                                            border.color: Theme.border
                                            Text {
                                                anchors.centerIn: parent
                                                text: "−"
                                                font.pixelSize: Theme.fontSizeLarge
                                                font.bold: true
                                                color: Theme.text
                                            }
                                        }
                                        contentItem: TextInput {
                                            text: spin.textFromValue(spin.value, spin.locale)
                                            font: spin.font
                                            color: Theme.accentGreen
                                            selectionColor: Theme.highlight
                                            horizontalAlignment: Qt.AlignHCenter
                                            verticalAlignment: Qt.AlignVCenter
                                            readOnly: !spin.editable
                                            validator: spin.validator
                                            inputMethodHints: spin.inputMethodHints
                                            leftPadding: Theme.touchTargetMin
                                            rightPadding: Theme.touchTargetMin
                                            selectByMouse: true
                                        }
                                        background: Rectangle {
                                            color: Theme.bg
                                            border.color: spin.activeFocus ? Theme.highlight : Theme.border
                                            radius: Theme.radiusS
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Repeater {
                        model: pageCol.g ? pageCol.g.bools : []
                        delegate: Item {
                            required property var modelData
                            width: leftCol.width
                            height: 56
                            Switch {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.name
                                checked: modelData.default
                                onToggled: {
                                    if (modelData.momentary) return
                                    pageCol._sendBool(modelData.index, checked)
                                }
                            }
                        }
                    }
                }

                // Rechts: Joystick(s)
                Column {
                    width: pageCol.width * 0.34
                    spacing: Theme.spacingM
                    visible: pageCol.g && pageCol.g.joysticks.length > 0

                    Repeater {
                        model: pageCol.g ? pageCol.g.joysticks : []
                        delegate: Column {
                            required property var modelData
                            spacing: Theme.spacingXs
                            Text { text: modelData.name; color: Theme.accentBlue; font.bold: true }
                            Joystick {
                                xRangeMin: modelData.xRange[0]; xRangeMax: modelData.xRange[1]
                                yRangeMin: modelData.yRange[0]; yRangeMax: modelData.yRange[1]
                                returnToCenter: modelData.returnToCenter
                                onMoved: (x, y) => {
                                    if (pageCol.g.kind === "fast") {
                                        params.setFastFloat(modelData.xIndex, x)
                                        params.setFastFloat(modelData.yIndex, y)
                                    } else {
                                        params.setSlowFloat(modelData.xIndex, x)
                                        params.setSlowFloat(modelData.yIndex, y)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            function _sendFloat(index, value) {
                if (g.kind === "fast") params.setFastFloat(index, value)
                else params.setSlowFloat(index, value)
            }
            function _sendBool(index, value) {
                params.setSlowBool(index, value)
            }
        }
    }
}
