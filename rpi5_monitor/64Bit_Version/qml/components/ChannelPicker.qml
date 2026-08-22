import QtQuick
import QtQuick.Controls
import App

// Kanalauswahl für den Overlay-Editor.
//
// Bei 200 Kanälen ist ein ComboBox unbedienbar (200 Zeilen scrollen) und die
// nackte Nummer sagt nichts. Deshalb: Suchfeld über Nummer UND Name, darunter
// eine ListView mit touchtauglichen Zeilen.
//
// Gefiltert wird in JavaScript über ein Array — bei 200 Einträgen sind das
// pro Tastendruck 200 Vergleiche, also nichts. Ein QAbstractListModel mit
// QSortFilterProxyModel wäre hier reiner Aufwand ohne Gewinn.
Popup {
    id: root

    property var channelNames: []      // "  0  Motor_L_Speed", ...
    property bool allowNone: false
    property int current: 0

    signal picked(int channel)

    modal: true
    focus: true
    // Feste Breite: die Kinder binden an parent.width, eine aus dem Inhalt
    // abgeleitete Popup-Breite waere eine Bindungsschleife.
    width: Math.min(560, parent ? parent.width * 0.9 : 560)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    padding: Theme.spacingS

    property string _query: ""

    // {idx, text} — idx ist die echte Kanalnummer, nicht der Listenplatz.
    readonly property var _filtered: {
        var out = []
        var q = _query.trim().toLowerCase()
        if (root.allowNone && (q === "" || "kein".indexOf(q) === 0))
            out.push({ idx: -1, text: "— kein Kanal —" })
        for (var i = 0; i < root.channelNames.length; i++) {
            var t = String(root.channelNames[i])
            if (q === "" || t.toLowerCase().indexOf(q) !== -1)
                out.push({ idx: i, text: t })
        }
        return out
    }

    onOpened: {
        _query = ""
        searchField.text = ""
        searchField.forceActiveFocus()
        // Zum aktuellen Kanal springen — sonst startet man bei 200 Einträgen
        // immer oben und sucht seinen eigenen Wert. Qt.callLater, weil die
        // ListView im onOpened noch nicht aufgebaut ist und
        // positionViewAtIndex dann ins Leere liefe.
        Qt.callLater(function () {
            for (var i = 0; i < root._filtered.length; i++) {
                if (root._filtered[i].idx === root.current) {
                    list.positionViewAtIndex(i, ListView.Center)
                    return
                }
            }
        })
    }

    background: Rectangle {
        color: Theme.bgMid
        border.color: Theme.border
        border.width: 1
        radius: Theme.radiusM
    }

    contentItem: Column {
        width: root.availableWidth
        spacing: Theme.spacingS

        Text {
            width: parent.width
            text: "Kanal wählen"
            color: Theme.text
            font.bold: true
            font.pixelSize: Theme.fontSizeLarge
        }

        TextField {
            id: searchField
            width: parent.width
            height: Theme.touchTargetMin
            placeholderText: "Nummer oder Name suchen …"
            color: Theme.text
            font.pixelSize: Theme.fontSizeBase
            selectByMouse: true
            onTextChanged: root._query = text
        }

        ListView {
            id: list
            width: parent.width
            height: Math.min(420, root.parent ? root.parent.height * 0.5 : 420)
            clip: true
            model: root._filtered
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                required property var modelData
                width: list.width
                height: Theme.touchTargetMin
                color: modelData.idx === root.current ? Theme.bgAlt : "transparent"

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spacingS
                    anchors.right: parent.right
                    text: modelData.text
                    color: Theme.text
                    font.family: Theme.fontMono
                    font.pixelSize: Theme.fontSizeBase
                    elide: Text.ElideRight
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 1
                    color: Theme.border
                    opacity: 0.4
                }
                TapHandler {
                    onTapped: {
                        root.picked(modelData.idx)
                        root.close()
                    }
                }
            }
        }

        AppButton {
            width: parent.width
            text: "Abbrechen"
            onClicked: root.close()
        }
    }
}
