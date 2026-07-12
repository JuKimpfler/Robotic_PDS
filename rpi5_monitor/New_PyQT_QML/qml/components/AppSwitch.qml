import QtQuick
import App

// Ersatz für QtQuick.Controls "Switch" bei Bool-Parametern vom Typ
// "toggle". Die generische Material-Switch sah nicht wie ein "echter"
// Schalter aus und war visuell kaum von einem Button zu unterscheiden.
// Design 1:1 nach dem alten _SWITCH_STYLE aus Old_PySide/gui/tab_params.py:
// graue Pille im Ruhezustand, grün gefüllt + dunkelgrüner Text wenn an.
Item {
    id: root
    property string text: ""
    property bool checked: false
    signal toggled()

    implicitWidth: Math.max(140, nameLbl.implicitWidth + 32)
    implicitHeight: 56

    readonly property color _onBg:   "#2ecc71"
    readonly property color _onTxt:  "#10331d"
    readonly property color _offBg:  "#3a3a3a"
    readonly property color _offTxt: "#cccccc"

    Rectangle {
        anchors.fill: parent
        radius: 10
        border.width: 2
        border.color: root.checked ? "#2ecc71" : "#444444"
        color: root.checked ? root._onBg
             : tap.pressed  ? "#4a4a4a"
             : root._offBg
        Behavior on color { ColorAnimation { duration: 100 } }

        Column {
            anchors.centerIn: parent
            spacing: 2
            Text {
                id: nameLbl
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.text
                color: root.checked ? root._onTxt : root._offTxt
                font.bold: true
                font.pixelSize: Theme.fontSizeBase
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.checked ? "AN" : "AUS"
                color: root.checked ? root._onTxt : root._offTxt
                font.pixelSize: Theme.fontSizeSmall
            }
        }
    }

    TapHandler {
        id: tap
        onTapped: { root.checked = !root.checked; root.toggled() }
    }
}
