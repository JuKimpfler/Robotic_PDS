import QtQuick
import QtQuick.Controls
import App

// Bedienfeld des Overlay-Editors — steht in der Systemansicht rechts, wo im
// Normalbetrieb die Grafiken liegen.
//
// Aufbau von oben nach unten:
//   1. Gruppe (Name, Hintergrundbild, Gruppe anlegen/löschen)
//   2. "＋ Element hinzufügen" — Auswahl der sieben Element-Arten
//   3. Liste aller Elemente der Gruppe (Antippen wählt aus)
//   4. Formular des ausgewählten Elements (FieldEditor, datengetrieben)
//   5. Aktionen für das ausgewählte Element
//
// Das Formular kennt KEINE Element-Art: es rendert stur, was
// visuals.selectedFields liefert (siehe overlay_schema.py). Deshalb steht
// hier nichts über Zeiger, Vektoren oder Feldansichten.
//
// Gelayoutet wird mit ANKERN, nicht mit einer Column: der Formularbereich
// soll "alles, was oben übrig bleibt" hoch sein. In einer Column wäre das
// `height: parent.height - y`, und da die Column das y aus den Höhen ihrer
// Kinder errechnet, wäre genau das eine Bindungsschleife.
Item {
    id: root

    property var visuals: null

    signal pickChannelRequested(string key, int current, bool allowNone)

    readonly property bool hasSelection: visuals !== null && visuals.selectedIndex >= 0

    // ══════════════════════════════════════════════════════════════════════
    //  1.-3. Gruppe, Hinzufügen, Liste
    // ══════════════════════════════════════════════════════════════════════
    Column {
        id: topCol
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Theme.spacingS

        Rectangle {
            width: parent.width
            height: groupCol.implicitHeight + 2 * Theme.spacingS
            color: Theme.bgMid
            radius: Theme.radiusM

            Column {
                id: groupCol
                x: Theme.spacingS
                y: Theme.spacingS
                // Math.max: ist der Editor ausgeblendet, ist die Breite 0
                // und die Differenz waere negativ.
                width: Math.max(0, parent.width - 2 * Theme.spacingS)
                spacing: Theme.spacingXs

                Text {
                    text: "Gruppe"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSizeSmall
                }
                TextField {
                    width: parent.width
                    height: Theme.touchTargetMin
                    text: root.visuals ? root.visuals.activeGroup.name : ""
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeBase
                    selectByMouse: true
                    onEditingFinished: root.visuals.renameGroup(text)
                }

                Text {
                    text: "Hintergrundbild"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSizeSmall
                }
                Flow {
                    width: parent.width
                    spacing: Theme.spacingXs
                    Repeater {
                        model: root.visuals ? root.visuals.imageChoices : []
                        delegate: AppButton {
                            required property var modelData
                            width: Math.round(96 * Theme.fontScale)
                            height: Theme.touchTargetMin
                            text: modelData.label
                            checkable: true
                            // Nur gebunden, nie zugewiesen — sonst wäre die
                            // Bindung nach dem ersten Antippen zerstört.
                            checked: root.visuals.activeGroup.imageIdx === modelData.idx
                            onClicked: root.visuals.setGroupImage(modelData.idx)
                        }
                    }
                }

                Row {
                    width: parent.width
                    spacing: Theme.spacingXs
                    AppButton {
                        width: (parent.width - Theme.spacingXs) / 2
                        height: Theme.touchTargetMin
                        text: "＋ Gruppe"
                        onClicked: root.visuals.addGroup()
                    }
                    AppButton {
                        width: (parent.width - Theme.spacingXs) / 2
                        height: Theme.touchTargetMin
                        text: "🗑 Gruppe"
                        onClicked: root.visuals.removeGroup()
                    }
                }
            }
        }

        AppButton {
            width: parent.width
            height: Theme.touchTargetMin
            text: "＋ Element hinzufügen"
            onClicked: addPopup.open()
        }

        Rectangle {
            width: parent.width
            height: Math.max(Math.round(120 * Theme.fontScale), root.height * 0.24)
            color: Theme.bgMid
            radius: Theme.radiusM
            clip: true

            ListView {
                id: entryList
                anchors.fill: parent
                anchors.margins: 2
                model: root.visuals ? root.visuals.entryList : []
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // Der Editor liegt in einem SwipeView — beim Scrollen der
                // Liste darf nicht der Tab wechseln.
                onMovingChanged: moving ? UiState.pushLock() : UiState.popLock()

                delegate: Rectangle {
                    id: entryRow
                    required property var modelData
                    width: entryList.width
                    height: Theme.touchTargetMin
                    color: modelData.selected ? Theme.bgAlt : "transparent"

                    Rectangle {
                        anchors.left: parent.left
                        width: 4
                        height: parent.height
                        color: entryRow.modelData.selected ? Theme.highlight : "transparent"
                    }
                    Text {
                        id: kindLbl
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.spacingS
                        width: Math.round(80 * Theme.fontScale)
                        text: entryRow.modelData.kindLabel
                        color: Theme.accentBlue
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: kindLbl.right
                        anchors.leftMargin: Theme.spacingXs
                        anchors.right: warnLbl.left
                        text: entryRow.modelData.summary
                        color: Theme.text
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                    Text {
                        id: warnLbl
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.spacingS
                        width: entryRow.modelData.problems > 0 ? implicitWidth : 0
                        visible: entryRow.modelData.problems > 0
                        text: "⚠"
                        color: Theme.accentAmber
                        font.pixelSize: Theme.fontSizeBase
                    }
                    TapHandler {
                        onTapped: root.visuals.select(entryRow.modelData.list,
                                                      entryRow.modelData.index)
                    }
                }
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    //  4. + 5. Formular und Aktionen
    // ══════════════════════════════════════════════════════════════════════
    Item {
        id: formArea
        anchors.top: topCol.bottom
        anchors.topMargin: Theme.spacingS
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        Text {
            anchors.centerIn: parent
            width: parent.width - 2 * Theme.spacingM
            visible: !root.hasSelection
            text: "Element in der Liste oder direkt im Bild antippen.\n\n"
                  + "Text-Elemente lassen sich im Bild verschieben; bei einem "
                  + "Textraster zieht man damit den ganzen Block."
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeBase
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }

        // Warnungen (fehlende Kanäle, Minimum >= Maximum, ...). Bewusst nur
        // Hinweis und keine Sperre: ein Element mit einem Kanal, den es noch
        // nicht gibt, muss sich weiter bearbeiten und speichern lassen.
        Rectangle {
            id: problemBox
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: visible ? problemCol.implicitHeight + Theme.spacingS : 0
            visible: root.hasSelection && root.visuals.selectedProblems.length > 0
            color: Theme.warnBg
            radius: Theme.radiusS

            Column {
                id: problemCol
                x: Theme.spacingS
                y: Theme.spacingXs
                width: parent.width - 2 * Theme.spacingS
                Repeater {
                    model: root.visuals ? root.visuals.selectedProblems : []
                    delegate: Text {
                        required property var modelData
                        width: problemCol.width
                        text: "⚠ " + modelData
                        color: Theme.accentAmber
                        font.pixelSize: Theme.fontSizeSmall
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        Row {
            id: actionRow
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: Theme.touchTargetMin
            visible: root.hasSelection
            spacing: Theme.spacingXs

            readonly property real bw: (width - 3 * Theme.spacingXs) / 4

            AppButton {
                width: actionRow.bw; height: parent.height
                text: "▲"
                onClicked: root.visuals.moveSelectedInList(-1)
            }
            AppButton {
                width: actionRow.bw; height: parent.height
                text: "▼"
                onClicked: root.visuals.moveSelectedInList(1)
            }
            AppButton {
                width: actionRow.bw; height: parent.height
                text: "⧉ Kopie"
                onClicked: root.visuals.duplicateSelected()
            }
            AppButton {
                width: actionRow.bw; height: parent.height
                text: "🗑"
                danger: true
                onClicked: root.visuals.removeSelected()
            }
        }

        Flickable {
            anchors.top: problemBox.bottom
            anchors.topMargin: problemBox.visible ? Theme.spacingS : 0
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: actionRow.top
            anchors.bottomMargin: Theme.spacingS
            visible: root.hasSelection
            contentHeight: fieldCol.height
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            onMovingChanged: moving ? UiState.pushLock() : UiState.popLock()

            Column {
                id: fieldCol
                width: parent.width
                spacing: Theme.spacingS

                Text {
                    text: root.visuals ? root.visuals.selectedKindLabel : ""
                    color: Theme.accentBlue
                    font.bold: true
                    font.pixelSize: Theme.fontSizeBase
                }

                Repeater {
                    model: root.visuals ? root.visuals.selectedFields : []
                    delegate: FieldEditor {
                        required property var modelData
                        width: fieldCol.width
                        field: modelData
                        channelNames: root.visuals.channelNames
                        colorPresets: root.visuals.colorPresets
                        onCommit: (key, value) => root.visuals.setField(key, value)
                        onRequestChannelPick: (key, current) =>
                            root.pickChannelRequested(key, current,
                                                      modelData.allowNone === true)
                    }
                }
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    //  Auswahl der Element-Art
    // ══════════════════════════════════════════════════════════════════════
    //  Eine gemeinsame Liste statt zweier Repeater: eine Inline-Komponente
    //  ließe sich nur im Wurzelobjekt der Datei deklarieren, und denselben
    //  Delegaten zweimal hinzuschreiben wäre die schlechtere Antwort.
    //  `section` trägt die Zwischenüberschrift der ersten Zeile ihrer Gruppe.
    readonly property var _kindModel: {
        var out = []
        if (!root.visuals) return out
        var src = [{ title: "Auf dem Bild", list: root.visuals.overlayKinds },
                   { title: "Neben dem Bild", list: root.visuals.graphicKinds }]
        for (var s = 0; s < src.length; s++) {
            for (var i = 0; i < src[s].list.length; i++) {
                var k = src[s].list[i]
                out.push({ kind: k.kind, label: k.label, hint: k.hint,
                           section: i === 0 ? src[s].title : "" })
            }
        }
        return out
    }

    Popup {
        id: addPopup
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        width: Math.min(560, parent ? parent.width * 0.9 : 560)
        padding: Theme.spacingS

        background: Rectangle {
            color: Theme.bgMid
            border.color: Theme.border
            border.width: 1
            radius: Theme.radiusM
        }

        contentItem: Column {
            width: addPopup.availableWidth
            spacing: Theme.spacingXs

            Text {
                width: parent.width
                text: "Was soll dazu?"
                color: Theme.text
                font.bold: true
                font.pixelSize: Theme.fontSizeLarge
            }

            Repeater {
                model: root._kindModel
                delegate: Column {
                    id: kindEntry
                    required property var modelData
                    width: addPopup.availableWidth
                    spacing: Theme.spacingXs

                    Text {
                        width: parent.width
                        visible: kindEntry.modelData.section !== ""
                        height: visible ? implicitHeight : 0
                        text: kindEntry.modelData.section
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSizeSmall
                        topPadding: Theme.spacingXs
                    }

                    // Bezeichnung fett, darunter wozu es gut ist: ohne den
                    // Zusatz ist "Textraster" gegen "Tabelle" nicht zu raten.
                    Rectangle {
                        width: parent.width
                        height: Math.round(60 * Theme.fontScale)
                        radius: Theme.radiusS
                        color: kindTap.pressed ? Theme.highlight : Theme.bgInput
                        border.color: Theme.border
                        border.width: 1

                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: Theme.spacingS
                            anchors.right: parent.right
                            anchors.rightMargin: Theme.spacingS
                            Text {
                                text: kindEntry.modelData.label
                                color: Theme.text
                                font.bold: true
                                font.pixelSize: Theme.fontSizeBase
                            }
                            Text {
                                width: parent.width
                                text: kindEntry.modelData.hint
                                color: Theme.textDim
                                font.pixelSize: Theme.fontSizeSmall
                                elide: Text.ElideRight
                            }
                        }
                        TapHandler {
                            id: kindTap
                            onTapped: {
                                root.visuals.addEntry(kindEntry.modelData.kind)
                                addPopup.close()
                            }
                        }
                    }
                }
            }

            AppButton {
                width: parent.width
                text: "Abbrechen"
                onClicked: addPopup.close()
            }
        }
    }

    function openAddDialog() { addPopup.open() }
}
