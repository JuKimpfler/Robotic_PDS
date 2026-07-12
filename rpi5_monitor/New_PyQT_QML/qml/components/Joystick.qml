import QtQuick
import App

// Ersatz für gui/tab_params.py::JoystickWidget. Statt mousePressEvent/
// mouseMoveEvent (nur Maus) wird hier ein echter QML PointHandler
// verwendet, der Maus UND Touch gleichermaßen abdeckt.
Item {
    id: root
    implicitWidth: 220
    implicitHeight: 220

    property real xRangeMin: -100
    property real xRangeMax: 100
    property real yRangeMin: -100
    property real yRangeMax: 100
    property bool returnToCenter: true

    // Aktueller Wert im konfigurierten Bereich (nicht normiert)
    property real valueX: 0
    property real valueY: 0

    signal moved(real x, real y)

    readonly property real _r: Math.min(width, height) / 2 - 14
    readonly property point _center: Qt.point(width / 2, height / 2)

    // normierte Knopf-Position -1..1
    property real _knobX: 0
    property real _knobY: 0
    property bool _dragging: false

    Behavior on _knobX { enabled: !root._dragging; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
    Behavior on _knobY { enabled: !root._dragging; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.centerIn: parent
        width: root._r * 2; height: width
        radius: width / 2
        color: Theme.bg
        border.color: Theme.border
        border.width: 2
    }

    // Fadenkreuz
    Rectangle { anchors.centerIn: parent; width: root._r * 2 - 8; height: 1; color: Theme.border }
    Rectangle { anchors.centerIn: parent; width: 1; height: root._r * 2 - 8; color: Theme.border }

    Rectangle {
        id: knob
        width: 34; height: 34; radius: 17
        color: root._dragging ? Theme.ledOn : Qt.darker(Theme.ledOn, 1.3)
        border.color: Theme.ledOn
        border.width: 2
        x: root._center.x + root._knobX * root._r - width / 2
        y: root._center.y + root._knobY * root._r - height / 2
    }

    PointHandler {
        id: pointHandler
        target: null
        onActiveChanged: {
            root._dragging = active
            if (!active && root.returnToCenter) {
                root._knobX = 0
                root._knobY = 0
                root._emit()
            }
        }
        onPointChanged: {
            if (!active) return
            var dx = (point.position.x - root._center.x) / root._r
            var dy = (point.position.y - root._center.y) / root._r
            var mag = Math.hypot(dx, dy)
            if (mag > 1.0) { dx /= mag; dy /= mag }
            root._knobX = dx
            root._knobY = dy
            root._emit()
        }
    }

    function _emit() {
        var x = _knobX * (_knobX >= 0 ? xRangeMax : -xRangeMin)
        var y = -_knobY * (-_knobY >= 0 ? yRangeMax : -yRangeMin)   // Bildschirm-Y invertieren
        valueX = x
        valueY = y
        moved(x, y)
    }
}
