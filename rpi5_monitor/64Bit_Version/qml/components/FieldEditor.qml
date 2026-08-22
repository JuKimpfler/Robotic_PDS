import QtQuick
import QtQuick.Controls
import App

// Ein einzelnes Feld des Overlay-Editors.
//
// WARUM GENERISCH: die Systemansicht kennt sieben Arten von Anzeige-Elementen
// mit je eigenen Feldern. Ein Formular je Art wären sieben fast gleiche
// QML-Blöcke, und ein neues Feld müsste in allen nachgezogen werden.
// Stattdessen beschreibt overlay_schema.py die Felder als Daten
// ({key, label, type, value, min, max, step, ...}) und dieses Element
// rendert daraus das passende Bedienelement. Ein neues Feld ist damit eine
// Zeile Python und hier gar nichts.
//
// Geschrieben wird nie direkt: `commit(key, value)` geht an
// VisualsBridge.setField(), das die Typumwandlung und die Wertebereiche
// zentral in overlay_schema.coerce() erledigt. Ein Textfeld liefert in QML
// immer eine Zeichenkette — ohne diese eine Stelle stünde "12" als Text in
// der JSON-Datei.
Item {
    id: root

    property var field: ({})          // ein Eintrag aus visuals.selectedFields
    property var channelNames: []     // für type "channel": Anzeige des Namens
    property var colorPresets: []

    signal commit(string key, var value)
    signal requestChannelPick(string key, int current)

    readonly property string fType: field.type || "text"
    readonly property string fKey:  field.key || ""

    implicitHeight: col.implicitHeight
    height: implicitHeight

    function _num(v, fallback) {
        var n = Number(v)
        return isNaN(n) ? fallback : n
    }
    readonly property real fStep: _num(field.step, 1)
    readonly property int  fDecimals: fType === "real" ? _num(field.decimals, 1) : 0

    function _fmt(v) {
        return fType === "real" ? _num(v, 0).toFixed(fDecimals)
                                : String(Math.round(_num(v, 0)))
    }

    // Schrittweise ändern (die Wertebereiche prüft Python nochmals).
    function _bump(delta) {
        root.commit(root.fKey, root._num(root.field.value, 0) + delta)
    }

    Column {
        id: col
        width: parent.width
        spacing: Theme.spacingXs

        Text {
            width: parent.width
            text: root.field.label || ""
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideRight
        }

        // ── text / channels ───────────────────────────────────────────────
        Loader {
            width: parent.width
            visible: active
            active: root.fType === "text" || root.fType === "channels"
            sourceComponent: TextField {
                width: parent.width
                height: Theme.touchTargetMin
                text: root.field.value !== undefined ? String(root.field.value) : ""
                color: Theme.text
                font.pixelSize: Theme.fontSizeBase
                font.family: root.fType === "channels"
                             ? Theme.fontMono : Qt.application.font.family
                selectByMouse: true
                // editingFinished deckt Verlassen des Feldes UND Enter ab —
                // auf dem Touchscreen gibt es kein zuverlässiges "fertig".
                onEditingFinished: root.commit(root.fKey, text)
            }
        }

        // ── int / real ────────────────────────────────────────────────────
        Loader {
            width: parent.width
            visible: active
            active: root.fType === "int" || root.fType === "real"
            sourceComponent: Row {
                width: parent.width
                spacing: Theme.spacingXs

                AppButton {
                    width: Theme.touchTargetMin
                    height: Theme.touchTargetMin
                    text: "−"
                    onClicked: root._bump(-root.fStep)
                }
                TextField {
                    width: parent.width - 2 * Theme.touchTargetMin - 2 * Theme.spacingXs
                    height: Theme.touchTargetMin
                    text: root._fmt(root.field.value)
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeBase
                    font.family: Theme.fontMono
                    horizontalAlignment: TextInput.AlignHCenter
                    selectByMouse: true
                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                    onEditingFinished: root.commit(root.fKey, text)
                }
                AppButton {
                    width: Theme.touchTargetMin
                    height: Theme.touchTargetMin
                    text: "+"
                    onClicked: root._bump(root.fStep)
                }
            }
        }

        // ── bool ──────────────────────────────────────────────────────────
        Loader {
            width: parent.width
            visible: active
            active: root.fType === "bool"
            sourceComponent: AppSwitch {
                width: parent.width
                text: root.field.value ? "an" : "aus"
                checked: root.field.value === true
                onToggled: (value) => root.commit(root.fKey, value)
            }
        }

        // ── color ─────────────────────────────────────────────────────────
        //  Feste Auswahl statt Farbrad: acht antippbare Felder trifft man auf
        //  einem 13"-Touchscreen, einen Farbkreis nicht.
        Loader {
            width: parent.width
            visible: active
            active: root.fType === "color"
            sourceComponent: Flow {
                width: parent.width
                spacing: Theme.spacingXs
                Repeater {
                    model: root.colorPresets
                    delegate: Rectangle {
                        required property var modelData
                        width: Theme.touchTargetMin
                        height: Theme.touchTargetMin
                        radius: Theme.radiusS
                        color: modelData
                        border.width: String(root.field.value) === String(modelData) ? 3 : 1
                        border.color: String(root.field.value) === String(modelData)
                                      ? Theme.text : Theme.border
                        TapHandler { onTapped: root.commit(root.fKey, modelData) }
                    }
                }
            }
        }

        // ── channel ───────────────────────────────────────────────────────
        //  Zahl UND Name: die Nummer allein sagt bei 200 Kanälen nichts.
        Loader {
            width: parent.width
            visible: active
            active: root.fType === "channel"
            sourceComponent: Row {
                width: parent.width
                spacing: Theme.spacingXs

                AppButton {
                    width: Theme.touchTargetMin
                    height: Theme.touchTargetMin
                    text: "−"
                    onClicked: root._bump(-1)
                }
                AppButton {
                    id: pickBtn
                    width: parent.width - 2 * Theme.touchTargetMin - 2 * Theme.spacingXs
                    height: Theme.touchTargetMin
                    text: {
                        var c = Math.round(root._num(root.field.value, -1))
                        if (c < 0) return "— kein Kanal —"
                        var n = (c < root.channelNames.length) ? root.channelNames[c] : ""
                        return n !== "" ? n : ("Kanal " + c)
                    }
                    onClicked: root.requestChannelPick(
                        root.fKey, Math.round(root._num(root.field.value, 0)))
                }
                AppButton {
                    width: Theme.touchTargetMin
                    height: Theme.touchTargetMin
                    text: "+"
                    onClicked: root._bump(1)
                }
            }
        }

        // ── Hinweistext ───────────────────────────────────────────────────
        Text {
            width: parent.width
            visible: (root.field.hint || "") !== ""
            text: root.field.hint || ""
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeSmall
            font.italic: true
            wrapMode: Text.WordWrap
        }
    }
}
