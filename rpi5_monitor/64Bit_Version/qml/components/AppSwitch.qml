import QtQuick
import App

// Ersatz für QtQuick.Controls "Switch" bei Bool-Parametern vom Typ
// "toggle". Die generische Material-Switch sah nicht wie ein "echter"
// Schalter aus und war visuell kaum von einem Button zu unterscheiden.
// Design 1:1 nach dem alten _SWITCH_STYLE aus Old_PySide/gui/tab_params.py:
// graue Pille im Ruhezustand, grün gefüllt + dunkelgrüner Text wenn an.
// ── WARUM DER SCHALTER SICH NICHT SELBST UMLEGT ────────────────────────────
// Fruehere Fassung: `onTapped: { root.checked = !root.checked; root.toggled() }`.
// Diese Zuweisung ZERSTOERT in QML die Bindung an `checked` — ab dem ersten
// Antippen folgt der Schalter seiner Quelle nicht mehr. Solange es nur einen
// Weg zu einem Wert gab, fiel das nicht auf. Sobald derselbe Wert auch
// anderswo geaendert werden kann (Strg+D fuer das Farbschema, ein Reset der
// Parameter, eine Rueckmeldung des Teensy), bleibt der Schalter stehen und
// zeigt etwas anderes an als der Zustand tatsaechlich ist.
//
// Jetzt meldet der Schalter nur den GEWUENSCHTEN Wert und zeigt weiterhin
// stur seine Bindung an. Wer eine Python-Property bindet, bekommt die
// Aktualisierung ueber deren Signal zurueck; wer den Zustand in QML haelt,
// weist `checked` im Handler selbst zu (siehe Bool-Parameter in ParamsView).
Item {
    id: root
    property string text: ""
    property bool checked: false

    /// value = der gewuenschte neue Zustand (also !checked).
    signal toggled(bool value)

    implicitWidth: Math.max(140, nameLbl.implicitWidth + 32)
    implicitHeight: Math.round(56 * Theme.fontScale)
    opacity: enabled ? 1.0 : 0.45

    // Farben aus dem Theme statt fester Dunkel-Werte: im hellen Farbschema
    // stand ein ausgeschalteter Schalter sonst als fast schwarzer Klotz mit
    // hellgrauer Schrift auf der hellen Seite. Der Text auf dem gruenen
    // "AN" richtet sich nach dessen Helligkeit (dunkles Gruen im hellen
    // Schema -> weisse Schrift).
    readonly property color _onBg:   Theme.ledOn
    readonly property color _onTxt:  Theme.dark ? "#10331d" : "#ffffff"
    readonly property color _offBg:  Theme.bgInput
    readonly property color _offTxt: Theme.text

    Rectangle {
        anchors.fill: parent
        radius: 10
        border.width: 2
        border.color: root.checked ? root._onBg : Theme.border
        color: root.checked ? (tap.pressed ? Qt.darker(root._onBg, 1.15) : root._onBg)
             : tap.pressed  ? Theme.bgAlt
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
        onTapped: root.toggled(!root.checked)
    }
}
