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

    // ── Neu zeichnen nur, wenn man es sieht ──────────────────────────────
    // Der Bogen ist rund 190 px lang. Gezeichnet wird deshalb nur, wenn sich
    // die Stellung um mindestens einen halben Pixel geaendert hat — vorher
    // loeste JEDER Telemetrie-Tick (20/s je Tacho) ein komplettes Neuzeichnen
    // aus, auch wenn nur die sechste Nachkommastelle rauschte. Die Zahl
    // darunter ist ein Text und folgt dem Wert weiterhin exakt.
    readonly property int _step: Math.round(_frac * 400)
    on_StepChanged: canvas.requestPaint()

    // Farben aus dem Theme: mit den frueher festen Dunkel-Werten war die
    // hellgraue Nadel im hellen Farbschema nicht zu sehen. Ein Wechsel des
    // Schemas muss ausserdem neu zeichnen — ein Canvas merkt das nicht selbst.
    readonly property color _trackColor: Theme.bgInput
    readonly property color _needleColor: Theme.text
    readonly property color _okColor: Theme.accentGreen
    readonly property color _highColor: Theme.accentRed
    on_TrackColorChanged: canvas.requestPaint()
    on_NeedleColorChanged: canvas.requestPaint()
    on_OkColorChanged: canvas.requestPaint()
    on_HighColorChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        renderTarget: Canvas.FramebufferObject
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var cx = width / 2, cy = height * 0.78, r = Math.min(width, height * 1.3) / 2 - 8
            var frac = root._step / 400

            ctx.lineWidth = 10
            ctx.lineCap = "round"

            // Hintergrundbogen
            ctx.strokeStyle = root._trackColor
            ctx.beginPath()
            ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI, false)
            ctx.stroke()

            // Wertbogen — bei 0 gar nicht: mit runden Enden bliebe sonst
            // ein farbiger Punkt stehen, der wie ein kleiner Ausschlag wirkt.
            if (frac > 0) {
                ctx.strokeStyle = frac > 0.85 ? root._highColor : root._okColor
                ctx.beginPath()
                ctx.arc(cx, cy, r, Math.PI, Math.PI + frac * Math.PI, false)
                ctx.stroke()
            }

            // Nadel
            var ang = Math.PI + frac * Math.PI
            ctx.strokeStyle = root._needleColor
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.moveTo(cx + Math.cos(ang) * (r - 40), cy + Math.sin(ang) * (r - 40))
            ctx.lineTo(cx + Math.cos(ang) * (r - 10), cy + Math.sin(ang) * (r - 10))
            ctx.stroke()
        }
        Component.onCompleted: requestPaint()
        // Eine neue Groesse verwirft den Inhalt des Canvas.
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Column {
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 0
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.value.toFixed(2)
            color: root._frac > 0.85 ? root._highColor : root._okColor
            font.family: Theme.fontMono
            font.bold: true
            font.pixelSize: Theme.fontSizeBase
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            // Lange Namen kuerzen statt in den Nachbar-Tacho zu laufen.
            width: Math.min(implicitWidth, root.width)
            elide: Text.ElideRight
            text: root.label
            color: Theme.textDim
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
