import QtQuick
import App

// Ersatz für QtQuick.Controls "Button". Die Material-Button-Standard-
// darstellung (v.a. mit checkable:true, z.B. "Einfrieren") füllte sich
// bei checked=true komplett mit Akzentfarbe — optisch nicht mehr von
// einem Switch zu unterscheiden. Design orientiert sich an den alten
// QPushButton-Stilen aus Old_PySide/gui/tab_params.py: klar umrandeter,
// flacher Button mit sichtbarem Press-Feedback statt Flächenfüllung.
//
// Zwei Varianten:
//  - Normal (danger:false): neutraler, dunkler Button (z.B. "Löschen",
//    "Als Default speichern").
//  - danger:true: rote "Taster"-Optik wie die alten momentary-Buttons
//    (param_config.json widget:"button"), inkl. press/release-Zustand
//    über die `pressed`-Property für Momentary-Bedienung.
Item {
    id: root
    property string text: ""
    property bool checkable: false
    property bool checked: false
    property bool danger: false
    readonly property bool pressed: tap.pressed
    signal clicked()

    implicitWidth: Math.max(140, lbl.implicitWidth + 32)
    implicitHeight: 56

    Rectangle {
        anchors.fill: parent
        radius: 10
        border.width: 2
        border.color: root.danger ? "#7a2e2e" : Theme.border
        color: {
            if (root.danger) {
                if (tap.pressed) return "#ff4444"
                if (root.checked) return "#2ecc71"
                return "#a33333"
            }
            if (tap.pressed) return Theme.highlight
            if (root.checkable && root.checked) return Theme.bgAlt
            return Theme.bgInput
        }
        Behavior on color { ColorAnimation { duration: 80 } }

        // Kleiner Status-Indikator statt voller Flächenfüllung — macht
        // den Unterschied zu einem Switch deutlich, zeigt aber trotzdem
        // an, ob ein checkable Button gerade aktiv ist.
        Rectangle {
            visible: root.checkable && root.checked && !root.danger
            width: 8; height: 8; radius: 4
            color: Theme.accentGreen
            anchors.top: parent.top
            anchors.right: parent.right
            anchors.margins: 6
        }

        Text {
            id: lbl
            anchors.centerIn: parent
            text: root.text
            color: root.danger ? "#ffffff" : Theme.text
            font.bold: true
            font.pixelSize: Theme.fontSizeBase
        }
    }

    TapHandler {
        id: tap
        onTapped: {
            if (root.checkable) root.checked = !root.checked
            root.clicked()
        }
    }
}
