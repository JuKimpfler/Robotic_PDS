import QtQuick 2.15
import App 1.0

// Ersetzt die "rotation"-Grafik aus tab_visuals.py (z.B. Rad FL/FR/RL/RR).
// `value` ist eine vorzeichenbehaftete Drehrate/Geschwindigkeit, kein
// Winkel: ein Pfeil dreht sich dauerhaft im Uhrzeigersinn (value > 0)
// oder gegen den Uhrzeigersinn (value < 0), die Pfeillänge skaliert mit
// |value| relativ zu maxVal. Bei value == 0 steht der Pfeil still.
Item {
    id: root
    implicitWidth: 96
    implicitHeight: 116

    property string label: ""
    property real value: 0
    property real maxVal: 5

    readonly property real _dial_r: 38
    readonly property real _minLen: 8
    readonly property real _maxLen: _dial_r - 8
    readonly property real _len: _minLen + Math.max(0, Math.min(1, Math.abs(root.value) / (root.maxVal || 1))) * (_maxLen - _minLen)
    readonly property bool _cw: root.value >= 0
    readonly property color _arrowColor: root._cw ? Theme.accentAmber : "#c586c0"

    // Kontinuierliche Rotation: der Winkel wird per Timer aus der
    // aktuellen Drehrate fortgeschrieben (statt eines fixen Zielwinkels),
    // damit sich der Pfeil bei value != 0 sichtbar weiterdreht und
    // Richtung + Geschwindigkeit sofort bei Wertänderung reagieren.
    property real _angle: 0
    readonly property real _degPerSec: 90 * (Math.abs(root.value) / (root.maxVal || 1)) + (root.value !== 0 ? 40 : 0)

    Timer {
        interval: 16
        running: root.value !== 0
        repeat: true
        property real _lastT: -1
        onTriggered: {
            var now = Date.now()
            if (_lastT < 0) _lastT = now
            var dt = (now - _lastT) / 1000.0
            _lastT = now
            var dir = root._cw ? 1 : -1
            root._angle = (root._angle + dir * root._degPerSec * dt) % 360
        }
        onRunningChanged: if (!running) _lastT = -1
    }

    Rectangle {
        id: dial
        width: root._dial_r * 2; height: root._dial_r * 2; radius: root._dial_r
        anchors.horizontalCenter: parent.horizontalCenter
        color: Theme.bg
        border.color: Theme.border
        border.width: 2

        Item {
            anchors.centerIn: parent
            width: 1; height: 1
            rotation: root._angle

            Rectangle {
                width: 4; height: root._len
                radius: 2
                color: root._arrowColor
                x: -width / 2
                y: -height
            }
            // Pfeilspitze
            Rectangle {
                width: 11; height: 11
                rotation: 45
                color: root._arrowColor
                x: -width / 2
                y: -root._len - 5
            }
        }

        Rectangle {
            width: 8; height: 8; radius: 4
            anchors.centerIn: parent
            color: root._arrowColor
        }
    }

    Column {
        anchors.top: dial.bottom
        anchors.topMargin: 4
        anchors.horizontalCenter: parent.horizontalCenter
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: (root.value >= 0 ? "↻ " : "↺ ") + root.value.toFixed(2)
            color: root._arrowColor
            font.family: Theme.fontMono
            font.pixelSize: Theme.fontSizeSmall
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
