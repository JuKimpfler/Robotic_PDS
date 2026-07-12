import QtQuick
import App

// Kompakter Halbkreis-Tacho für die "graphics"-Einträge aus
// visuals_overlays.json (type == "gauge"). Ersetzt die entsprechende
// QPainter-Zeichenroutine aus der alten tab_visuals.py.
Item {
    id: root
    implicitWidth: 150
    implicitHeight: 120

    property string label: ""
    property real value: 0
    property real minVal: 0
    property real maxVal: 1

    readonly property real _frac: Math.max(0, Math.min(1, (value - minVal) / ((maxVal - minVal) || 1)))

    Canvas {
        id: canvas
        anchors.fill: parent
        renderTarget: Canvas.FramebufferObject
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var cx = width / 2, cy = height * 0.78, r = Math.min(width, height * 1.3) / 2 - 8

            ctx.lineWidth = 10
            ctx.lineCap = "round"

            // Hintergrundbogen
            ctx.strokeStyle = "#3c3f41"
            ctx.beginPath()
            ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI, false)
            ctx.stroke()

            // Wertbogen
            ctx.strokeStyle = root._frac > 0.85 ? "#f48771" : "#4ec9b0"
            ctx.beginPath()
            ctx.arc(cx, cy, r, Math.PI, Math.PI + root._frac * Math.PI, false)
            ctx.stroke()

            // Nadel
            var ang = Math.PI + root._frac * Math.PI
            ctx.strokeStyle = "#e0e0e0"
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.moveTo(cx + Math.cos(ang) * (r - 40), cy + Math.sin(ang) * (r - 40))
            ctx.lineTo(cx + Math.cos(ang) * (r - 10), cy + Math.sin(ang) * (r - 10))
            ctx.stroke()
        }
        Component.onCompleted: requestPaint()
    }

    Connections {
        target: root
        function onValueChanged() { canvas.requestPaint() }
    }

    Column {
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 0
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.value.toFixed(2)
            color: Theme.accentGreen
            font.family: Theme.fontMono
            font.bold: true
            font.pixelSize: Theme.fontSizeBase
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
