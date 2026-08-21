import QtQuick
import QtQuick.Controls
import App
import "components"

// Baut die komplette Parameter-Oberfläche deklarativ aus appBridge.params.groups
// auf (siehe param_bridge.py::_build_groups) — kein Python-Widget-Factory-Code.
// Der Werte-Zustand lebt in den Delegates; Python bekommt nur Change-Events
// zum Weitersenden und schickt bei einem Neuaufbau die Live-Werte mit.
//
// ── Suchfeld (F5) ───────────────────────────────────────────────────────────
// Ist etwas eingetippt, wird statt der gewählten Gruppe eine gruppenübergreifende
// Trefferliste angezeigt. Dafür trägt JEDER Eintrag sein `kind` ("fast"/"slow"/
// "bool") mit sich — sonst wüsste die Trefferliste nicht, in welchen Kanal ein
// geänderter Wert gehört.
Item {
    id: root
    property var params: appBridge.params

    // Gruppenübergreifende Suche. Läuft nur beim Tippen, nicht im Datentakt.
    function _search(query) {
        var q = query.trim().toLowerCase()
        var floats = [], bools = []
        if (q.length === 0)
            return { "kind": "search", "title": "Suche", "floats": floats,
                     "bools": bools, "joysticks": [] }
        var gs = params.groups
        for (var i = 0; i < gs.length; ++i) {
            var g = gs[i]
            for (var j = 0; j < g.floats.length; ++j)
                if (g.floats[j].name.toLowerCase().indexOf(q) >= 0) floats.push(g.floats[j])
            for (var k = 0; k < g.bools.length; ++k)
                if (g.bools[k].name.toLowerCase().indexOf(q) >= 0) bools.push(g.bools[k])
        }
        return { "kind": "search", "title": "Suche", "floats": floats,
                 "bools": bools, "joysticks": [] }
    }

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS
        visible: params.configError.length === 0

        // ── Toolbar ────────────────────────────────────────────────────────
        Rectangle {
            width: parent.width
            height: Math.round(56 * Theme.fontScale)
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
                    width: 380
                    elide: Text.ElideRight
                }

                AppSwitch {
                    text: "Übertragung aktiv"
                    checked: params.enabled
                    anchors.verticalCenter: parent.verticalCenter
                    onToggled: params.setEnabled(checked)
                }

                AppButton {
                    text: params.canUndo ? "↶ Rückgängig" : "↶"
                    enabled: params.canUndo
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: params.undo()
                }

                AppButton {
                    text: "Als Default speichern"
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: params.saveDefaults()
                }

                AppButton {
                    text: "Abweichungen (" + params.diffCount + ")"
                    enabled: params.diffCount > 0
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: diffPopup.open()
                }
            }
        }

        // ── Rückmeldung des Teensy (B6) ────────────────────────────────────
        // Der Downlink war bis hierher fire-and-forget: niemand hat gemerkt,
        // wenn ein Wert gar nicht angekommen ist. Jetzt meldet der Teensy 2x/s
        // zurück, was er wirklich hält.
        Rectangle {
            width: parent.width
            height: Math.round(34 * Theme.fontScale)
            radius: Theme.radiusM
            color: params.ackMismatches.length > 0 ? Theme.warnBg
                 : (params.ackAvailable ? Theme.okBg : Theme.bgMid)
            border.color: params.ackMismatches.length > 0 ? Theme.accentAmber
                        : (params.ackAvailable ? Theme.accentGreen : Theme.border)

            Row {
                anchors.fill: parent
                anchors.leftMargin: Theme.spacingS
                anchors.rightMargin: Theme.spacingS
                spacing: Theme.spacingS

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    font.pixelSize: Theme.fontSizeSmall
                    color: params.ackMismatches.length > 0 ? Theme.accentAmber
                         : (params.ackAvailable ? Theme.accentGreen : Theme.textDim)
                    text: (params.ackAvailable ? "↩ " : "· ") + params.ackText
                }
                AppButton {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: params.ackMismatches.length > 0
                    text: "anzeigen"
                    onClicked: ackPopup.open()
                }
            }
        }

        // ── Controller-Statusbanner ─────────────────────────────────────────
        Rectangle {
            width: parent.width
            height: Math.round(40 * Theme.fontScale)
            radius: Theme.radiusM
            visible: params.controller.connected || params.keyboardActive
            color: Theme.okBg
            border.color: Theme.accentGreen
            Text {
                anchors.fill: parent
                anchors.margins: Theme.spacingS
                verticalAlignment: Text.AlignVCenter
                color: Theme.accentGreen
                font.family: Theme.fontMono
                font.pixelSize: Theme.fontSizeSmall
                elide: Text.ElideRight
                text: params.controller.connected
                      ? "🎮  Controller verbunden: " + params.controller.name
                        + "  — Touch-Eingabe der Fast Params ist gesperrt."
                      : "⌨  Tastatursteuerung aktiv (WASD fahren, Q/E drehen, "
                        + "Shift schneller, R/F Dribbler, Leertaste Not-Aus)."
            }
        }

        // ── Gruppen-Auswahl + Suche ───────────────────────────────────────
        Row {
            id: selectorRow
            width: parent.width
            spacing: Theme.spacingS
            Label {
                text: "Gruppe:"
                color: Theme.accentBlue
                font.bold: true
                anchors.verticalCenter: parent.verticalCenter
            }
            ComboBox {
                id: groupCombo
                width: 300
                height: Theme.touchTargetMin
                enabled: searchField.text.length === 0
                model: params.groups.map(g => g.title)
            }
            TextField {
                id: searchField
                width: 300
                height: Theme.touchTargetMin
                placeholderText: "🔍 Parameter suchen …"
                inputMethodHints: Qt.ImhNoPredictiveText
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: searchField.text.length > 0
                color: Theme.textDim
                font.pixelSize: Theme.fontSizeSmall
                text: {
                    var r = root._search(searchField.text)
                    return (r.floats.length + r.bools.length) + " Treffer"
                }
            }
        }

        // ── Aktive Gruppen-Seite ─────────────────────────────────────────
        Flickable {
            width: parent.width
            height: parent.height - Math.round(56 * Theme.fontScale)
                    - Math.round(34 * Theme.fontScale)
                    - Theme.touchTargetMin - Theme.spacingS * 4
                    - ((params.controller.connected || params.keyboardActive)
                       ? (Math.round(40 * Theme.fontScale) + Theme.spacingS) : 0)
            clip: true
            contentHeight: pageLoader.item ? pageLoader.item.implicitHeight : 0
            // Während der Joystick bedient wird, soll diese Seite nicht
            // gleichzeitig mitscrollen (siehe UiState.qml).
            interactive: !UiState.navigationLocked
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Loader {
                id: pageLoader
                width: parent.width
                property var groupData: {
                    if (searchField.text.length > 0)
                        return root._search(searchField.text)
                    return params.groups.length > groupCombo.currentIndex
                           ? params.groups[groupCombo.currentIndex] : null
                }
                sourceComponent: groupPageComp
            }
        }
    }

    // ── Abweichungs-Fenster (B5) ────────────────────────────────────────
    Popup {
        id: diffPopup
        modal: true
        focus: true
        width: Math.min(root.width * 0.7, 620)
        height: Math.min(root.height * 0.7, 520)
        anchors.centerIn: Overlay.overlay
        padding: Theme.spacingM
        background: Rectangle { color: Theme.bgMid; border.color: Theme.border; radius: Theme.radiusM }

        Column {
            anchors.fill: parent
            spacing: Theme.spacingS

            Text {
                text: "Abweichungen vom gespeicherten Default"
                color: Theme.accentBlue
                font.bold: true
                font.pixelSize: Theme.fontSizeLarge
            }
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                color: Theme.textDim
                font.pixelSize: Theme.fontSizeSmall
                text: "Verglichen wird gegen param_defaults.h — also gegen den Stand, "
                      + "der zuletzt über \"Als Default speichern\" abgelegt wurde."
            }

            ListView {
                width: parent.width
                height: parent.height - 150
                clip: true
                model: params.diffEntries
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Row {
                    required property var modelData
                    width: parent ? parent.width : 0
                    height: Math.round(24 * Theme.fontScale)
                    spacing: Theme.spacingS
                    Text {
                        width: 220
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                        color: Theme.text
                        font.pixelSize: Theme.fontSizeSmall
                        text: modelData.name
                    }
                    Text {
                        width: 140
                        anchors.verticalCenter: parent.verticalCenter
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.accentAmber
                        text: modelData.current
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.textDim
                        text: "war " + modelData.reference
                    }
                }
            }

            Row {
                spacing: Theme.spacingS
                AppButton {
                    text: "Alle zurücksetzen"
                    danger: true
                    onClicked: { params.resetToDefaults(); diffPopup.close() }
                }
                AppButton {
                    text: "Schließen"
                    onClicked: diffPopup.close()
                }
            }
        }
    }

    // ── Rückmeldungs-Fenster (B6) ───────────────────────────────────────
    Popup {
        id: ackPopup
        modal: true
        focus: true
        width: Math.min(root.width * 0.7, 620)
        height: Math.min(root.height * 0.7, 520)
        anchors.centerIn: Overlay.overlay
        padding: Theme.spacingM
        background: Rectangle { color: Theme.bgMid; border.color: Theme.border; radius: Theme.radiusM }

        Column {
            anchors.fill: parent
            spacing: Theme.spacingS

            Text {
                text: "Soll (GUI) gegen Ist (Teensy)"
                color: Theme.accentBlue
                font.bold: true
                font.pixelSize: Theme.fontSizeLarge
            }
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                color: Theme.textDim
                font.pixelSize: Theme.fontSizeSmall
                text: "Weicht hier etwas ab, ist der Wert nicht angekommen — meist eine "
                      + "schlechte Funkstrecke oder ein neu gestarteter Teensy, der den "
                      + "Slow-Kanal noch nicht wieder empfangen hat."
            }

            ListView {
                width: parent.width
                height: parent.height - 150
                clip: true
                model: params.ackMismatches
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Row {
                    required property var modelData
                    width: parent ? parent.width : 0
                    height: Math.round(24 * Theme.fontScale)
                    spacing: Theme.spacingS
                    Text {
                        width: 220
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                        color: Theme.text
                        font.pixelSize: Theme.fontSizeSmall
                        text: modelData.name
                    }
                    Text {
                        width: 140
                        anchors.verticalCenter: parent.verticalCenter
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.accentGreen
                        text: "Soll " + modelData.current
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.accentRed
                        text: "Ist " + modelData.reference
                    }
                }
            }

            AppButton {
                text: "Schließen"
                onClicked: ackPopup.close()
            }
        }
    }

    // ── Fehleranzeige, falls param_config.json ungültig ist ──────────────
    Rectangle {
        anchors.fill: parent
        anchors.margins: Theme.spacingM
        visible: params.configError.length > 0
        color: Theme.errorBg
        radius: Theme.radiusM
        Text {
            anchors.fill: parent
            anchors.margins: Theme.spacingM
            wrapMode: Text.WordWrap
            color: Theme.accentRed
            font.family: Theme.fontMono
            text: "ACHTUNG: Die Parameter-Konfiguration ist ungültig — Parameter-Tab deaktiviert.\n\n"
                  + params.configError
                  + "\n\nQuelle: " + params.configSource
                  + "\n\nKorrigieren und die GUI neu starten."
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
                    width: (pageCol.g && pageCol.g.joysticks.length > 0)
                           ? pageCol.width * 0.62 : pageCol.width
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
                                    // Nur auf Fast-Einträgen greift der Controller ein
                                    // (Slow-Params bleiben immer per Touch bedienbar).
                                    externalControl: modelData.kind === "fast"
                                                     && params.controller.connected
                                    externalValue: params.controller.values.length > modelData.index
                                                   ? params.controller.values[modelData.index]
                                                   : modelData.default
                                    onMoved: (v) => pageCol._send(modelData, v)
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
                                        width: 160
                                        color: Theme.text
                                        anchors.verticalCenter: parent.verticalCenter
                                        elide: Text.ElideRight
                                    }
                                    SpinBox {
                                        id: spin
                                        height: Theme.touchTargetMin
                                        width: 190
                                        // editable:true = Eingabe per (USB-)Tastatur möglich,
                                        // zusätzlich zu den +/- Tasten.
                                        editable: true
                                        inputMethodHints: Qt.ImhFormattedNumbersOnly
                                        from: Math.round(modelData.min * 1000)
                                        to: Math.round(modelData.max * 1000)
                                        stepSize: Math.max(1, Math.round(modelData.step * 1000))
                                        readonly property bool _controllerActive:
                                            modelData.kind === "fast" && params.controller.connected
                                        enabled: !_controllerActive
                                        opacity: _controllerActive ? 0.55 : 1.0
                                        value: _controllerActive
                                               && params.controller.values.length > modelData.index
                                               ? Math.round(params.controller.values[modelData.index] * 1000)
                                               : Math.round(modelData.default * 1000)
                                        textFromValue: (v) => (v / 1000).toFixed(3)
                                        valueFromText: (t) => Math.round(parseFloat(t.replace(",", ".")) * 1000)
                                        onValueModified: pageCol._send(modelData, value / 1000)

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
                            height: Math.round(64 * Theme.fontScale)

                            // "toggle": normaler Ein/Aus-Schalter, Zustand bleibt bis
                            // zum nächsten Antippen erhalten.
                            AppSwitch {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: modelData.widget !== "button"
                                text: modelData.name
                                checked: modelData.default
                                onToggled: params.setSlowBool(modelData.index, checked)
                            }

                            // "button": Taster — bei momentary:true wird der Wert NUR
                            // gesendet solange gedrückt gehalten wird (true bei Press,
                            // false bei Release), bei momentary:false verhält er sich
                            // wie ein klickbarer Umschalt-Button.
                            AppButton {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: modelData.widget === "button"
                                danger: true
                                checkable: !modelData.momentary
                                checked: modelData.default
                                text: modelData.name
                                onPressedChanged: {
                                    if (modelData.momentary)
                                        params.setSlowBool(modelData.index, pressed)
                                }
                                onClicked: {
                                    if (!modelData.momentary)
                                        params.setSlowBool(modelData.index, checked)
                                }
                            }
                        }
                    }

                    Text {
                        visible: pageCol.g && pageCol.g.kind === "search"
                                 && pageCol.g.floats.length === 0
                                 && pageCol.g.bools.length === 0
                        color: Theme.textDim
                        text: "Keine Treffer."
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
                                // Nur der/die Joystick(s) auf der Fast-Seite werden vom
                                // Controller übernommen (Slow-Joysticks bleiben Touch).
                                externalControl: modelData.source === "fast"
                                                 && params.controller.connected
                                externalNormX: params.controller.stickNormX
                                externalNormY: params.controller.stickNormY
                                onMoved: (x, y) => {
                                    if (modelData.source === "fast") {
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

            // Der Zielkanal steckt im Eintrag selbst, nicht in der Gruppe —
            // sonst könnte die gruppenübergreifende Trefferliste einen Wert
            // in den falschen Kanal schreiben.
            function _send(entry, value) {
                if (entry.kind === "fast") params.setFastFloat(entry.index, value)
                else params.setSlowFloat(entry.index, value)
            }
        }
    }
}
