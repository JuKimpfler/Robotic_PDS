import QtQuick 2.15
import App 1.0

// Ersetzt TwoBodiesWidget (alte tab_visuals.py, QPainter) für den
// "bodies"-Grafiktyp aus visuals_overlays.json: ein Koordinatenfeld
// (Ursprung = Bildmitte, X+ rechts, Y+ oben) mit zwei Körpern, die per
// Kanalwert positioniert/gedreht werden.
//
// Das Feld hat ein festes Seitenverhältnis (RoboCup-Junior-Spielfeld:
// 243 x 182 cm) und wird NICHT verzerrt gestreckt: die Höhe passt sich
// wie bisher an den verfügbaren Platz an, die Breite wird daraus über
// das feste Verhältnis berechnet (und umgekehrt begrenzt, falls die
// Breite nicht ausreicht) -> das Feld ist immer zentriert und
// unverzerrt zu sehen ("Letterboxing" statt Stretch).
Item {
    id: root
    implicitWidth: 400
    implicitHeight: 300

    property string label: ""
    property string imageUrl: ""
    property real fieldWidth: 2.0
    property real fieldHeight: 1.5

    // Anzeige-Seitenverhältnis des Feldes (Breite:Höhe) — unabhängig von
    // fieldWidth/fieldHeight (die nur die Koordinaten-Skalierung für die
    // Kanalwerte bestimmen). RoboCup-Junior-Feld: 243 cm x 182 cm.
    readonly property real displayAspect: 243 / 182

    // { label, color, diameter, x, y, angleDeg }
    property var body1: ({ label: "", color: "#4ec9b0", diameter: 0.3, x: 0, y: 0, angleDeg: 0 })
    property var body2: ({ label: "", color: "#f0c060", diameter: 0.3, x: 0, y: 0, angleDeg: 0 })

    // ── Feldbox mit festem Seitenverhältnis, zentriert im verfügbaren
    // Platz. Höhe = verfügbare Höhe (wie bisher), Breite daraus über
    // displayAspect berechnet; passt die Breite nicht, wird stattdessen
    // von der Breite ausgehend gerechnet, damit nichts überläuft.
    Item {
        id: fieldBox
        readonly property real _byHeightW: root.height * root.displayAspect
        readonly property real _fitsWidth: _byHeightW <= root.width
        width: _fitsWidth ? _byHeightW : root.width
        height: _fitsWidth ? root.height : root.width / root.displayAspect
        anchors.centerIn: parent

        // Feldkoordinaten -> Pixel (Ursprung = Mitte, Y invertiert für Screen)
        function fieldToPxX(fx) { return (fx / root.fieldWidth + 0.5) * width }
        function fieldToPxY(fy) { return (0.5 - fy / root.fieldHeight) * height }
        readonly property real _diamScale: Math.min(width / root.fieldWidth, height / root.fieldHeight)

        Rectangle {
            anchors.fill: parent
            color: Theme.bg
            border.color: Theme.border
            border.width: 1.5
            radius: Theme.radiusS
            clip: true

            Image {
                anchors.fill: parent
                source: root.imageUrl
                fillMode: Image.Stretch
                asynchronous: true
                visible: root.imageUrl.length > 0
            }

            // Abdunkeln, damit Gitter/Körper auf dem Bild lesbar bleiben
            Rectangle { anchors.fill: parent; color: "#000000"; opacity: 0.35 }

            // ── Rasterlinien ──────────────────────────────────────────
            Canvas {
                id: grid
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = "rgba(60,120,200,0.35)"
                    ctx.lineWidth = 1
                    ctx.setLineDash([2, 4])

                    var step = Math.max(root.fieldWidth, root.fieldHeight) / 10.0
                    var xf = -root.fieldWidth / 2
                    while (xf <= root.fieldWidth / 2 + 1e-9) {
                        var px = fieldBox.fieldToPxX(xf)
                        ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, height); ctx.stroke()
                        xf += step
                    }
                    var yf = -root.fieldHeight / 2
                    while (yf <= root.fieldHeight / 2 + 1e-9) {
                        var py = fieldBox.fieldToPxY(yf)
                        ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(width, py); ctx.stroke()
                        yf += step
                    }

                    // Fadenkreuz durch den Ursprung
                    ctx.strokeStyle = "rgba(80,160,255,0.55)"
                    ctx.setLineDash([])
                    ctx.lineWidth = 1.2
                    var ox = fieldBox.fieldToPxX(0), oy = fieldBox.fieldToPxY(0)
                    ctx.beginPath(); ctx.moveTo(0, oy); ctx.lineTo(width, oy); ctx.stroke()
                    ctx.beginPath(); ctx.moveTo(ox, 0); ctx.lineTo(ox, height); ctx.stroke()
                }
                Component.onCompleted: requestPaint()
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
            }

            Text {
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.margins: 6
                text: root.label
                color: Theme.accentBlue
                font.bold: true
                font.pixelSize: Theme.fontSizeSmall
            }

            Repeater {
                model: [root.body1, root.body2]
                delegate: Item {
                    required property var modelData
                    readonly property real bx: fieldBox.fieldToPxX(modelData.x)
                    readonly property real by: fieldBox.fieldToPxY(modelData.y)
                    readonly property real rPx: Math.max(10, Math.abs(modelData.diameter) / 2 * fieldBox._diamScale)

                    x: bx - rPx; y: by - rPx
                    width: rPx * 2; height: rPx * 2

                    Behavior on x { NumberAnimation { duration: 80 } }
                    Behavior on y { NumberAnimation { duration: 80 } }

                    // Glow
                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.width + 16; height: parent.height + 16
                        radius: width / 2
                        color: modelData.color
                        opacity: 0.18
                    }

                    // Körper
                    Rectangle {
                        anchors.fill: parent
                        radius: width / 2
                        color: modelData.color
                        opacity: 0.72
                        border.color: modelData.color
                        border.width: 2.5
                    }

                    // Richtungspfeil (0° = rechts, + = im Uhrzeigersinn,
                    // Screen-Y nach unten entspricht das direkt CW)
                    Item {
                        anchors.centerIn: parent
                        width: parent.width; height: parent.height
                        rotation: modelData.angleDeg
                        Behavior on rotation { RotationAnimation { duration: 100; direction: RotationAnimation.Shortest } }

                        Rectangle {
                            width: Math.max(14, parent.width * 0.9)
                            height: 3
                            radius: 1.5
                            color: modelData.color
                            x: parent.width / 2
                            y: parent.height / 2 - height / 2
                        }
                        Rectangle {
                            width: 10; height: 10
                            rotation: 45
                            color: modelData.color
                            x: parent.width / 2 + Math.max(14, parent.width * 0.9) - 5
                            y: parent.height / 2 - 5
                        }
                    }

                    // Label über dem Körper (mit Hintergrund für Lesbarkeit)
                    Rectangle {
                        anchors.bottom: parent.top
                        anchors.bottomMargin: 4
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: lbl.implicitWidth + 10
                        height: lbl.implicitHeight + 4
                        radius: 2
                        color: "#000000"
                        opacity: 0.65
                    }
                    Text {
                        id: lbl
                        anchors.bottom: parent.top
                        anchors.bottomMargin: 6
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: modelData.label + "  " + modelData.angleDeg.toFixed(0) + "°"
                        color: modelData.color
                        font.bold: true
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
            }
        }
    }
}
