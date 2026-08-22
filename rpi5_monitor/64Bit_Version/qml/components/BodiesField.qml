import QtQuick
import App

// Spielfeld-Draufsicht mit zwei Körpern (Ball + Roboter) für den
// "bodies"-Grafiktyp.
//
// ════════════════════════════════════════════════════════════════════════════
//  KOORDINATENSYSTEM
// ════════════════════════════════════════════════════════════════════════════
//  Feldkoordinaten (das, was der Teensy schickt), Angaben in ZENTIMETERN:
//
//      x = 0 … fieldXCm   steigend nach RECHTS
//      y = 0 … fieldYCm   steigend nach OBEN
//      Ursprung (0,0) = linke UNTERE Ecke
//
//                    ┌──────────────┬──────────────┐
//                    │              │              │
//              y ▲   ├───┐          │          ┌───┤
//                │   │TOR│      ( • )          │TOR│
//                │   └───┤          │          ├───┘
//                │       │          │          │
//                    └──────────────┴──────────────┘
//                    (0,0) ──────────────────────► x
//
//  Die lange Achse ist die, die in der Konfiguration größer ist — bei einem
//  RoboCup-Junior-Feld also x = 240 cm, y = 180 cm, und damit Querformat.
//  Die Tore stehen an den Enden der LANGEN Achse und sind quer dazu mittig.
//
//  Warum genau so: die frühere Widgets-Oberfläche (gui/tab_visuals.py,
//  TwoBodiesWidget) hat es so gezeichnet — "Koordinaten: X=rechts, Y=oben" —
//  und alle vorhandenen Konfigurationen und Hintergrundbilder passen dazu.
//  Eine zwischenzeitliche Fassung drehte das Feld um 90 Grad und rechnete
//  field_width/field_height als METER; aus 240 × 180 cm wurde damit ein
//  240 × 180 METER großes Feld, in dem ein 45-cm-Tor 0,25 % der Kante
//  einnahm und die Rasterlinien alle 30 cm zu einer Fläche verschmolzen.
//
//  Der Winkel ist wie in der alten Oberfläche zu lesen: 0° = nach rechts,
//  positiv im Uhrzeigersinn. QML dreht genauso, deshalb wird der Wert
//  unverändert als `rotation` benutzt.
//
//  Das Feld wird NIE verzerrt gestreckt: das Seitenverhältnis ergibt sich
//  aus fieldXCm : fieldYCm, der Rest bleibt Rand ("Letterboxing").
Item {
    id: root
    implicitWidth: 400
    implicitHeight: 300

    property string label: ""
    property string imageUrl: ""

    // Feldmaße in cm — in derselben Einheit wie die Kanalwerte.
    property real fieldXCm: 240     // waagerecht
    property real fieldYCm: 180     // senkrecht

    // Tore an den Enden der LANGEN Achse, quer dazu mittig.
    // goalWidthCm ist die Toröffnung quer zur Spielrichtung.
    property real goalWidthCm: 45
    property real goalDepthCm: 10

    property real gridStepCm: 30
    property real centerCircleCm: 60

    // { label, color, diameter (cm), x (cm), y (cm), angleDeg }
    property var body1: ({ label: "", color: "#4ec9b0", diameter: 7,  x: 0, y: 0, angleDeg: 0 })
    property var body2: ({ label: "", color: "#f0c060", diameter: 18, x: 0, y: 0, angleDeg: 0 })

    readonly property bool hasImage: imageUrl.length > 0
    readonly property real displayAspect: (fieldYCm > 0 ? fieldXCm / fieldYCm : 4 / 3)

    Item {
        id: fieldBox
        readonly property real _byHeightW: root.height * root.displayAspect
        readonly property real _fitsWidth: _byHeightW <= root.width
        width: _fitsWidth ? _byHeightW : root.width
        height: _fitsWidth ? root.height : root.width / root.displayAspect
        anchors.centerIn: parent

        // Feldkoordinaten -> Pixel. y ist gespiegelt, weil die Bildschirm-
        // achse nach unten zeigt, die Feldachse aber nach oben.
        function xToPx(fx) { return (fx / Math.max(1, root.fieldXCm)) * width }
        function yToPx(fy) { return (1 - fy / Math.max(1, root.fieldYCm)) * height }

        // cm -> Pixel für Durchmesser (beide Achsen sind gleich skaliert,
        // solange das Seitenverhältnis stimmt — der kleinere Wert ist die
        // sichere Wahl).
        readonly property real _cmScale: Math.min(width / Math.max(1, root.fieldXCm),
                                                   height / Math.max(1, root.fieldYCm))

        Rectangle {
            anchors.fill: parent
            // Ohne Hintergrundbild ein gedämpftes Rasengrün, damit auf einen
            // Blick klar ist, dass hier ein Spielfeld steht.
            color: root.hasImage ? "transparent"
                                 : (Theme.dark ? "#16301f" : "#e3f0e6")
            border.color: Theme.border
            border.width: 1.5
            radius: Theme.radiusS
            clip: true

            Image {
                anchors.fill: parent
                source: root.imageUrl
                fillMode: Image.Stretch
                asynchronous: true
                visible: root.hasImage
            }

            // Abdunkeln, damit Gitter/Körper auf dem Bild lesbar bleiben
            Rectangle {
                anchors.fill: parent
                color: Theme.dark ? "#000000" : "#ffffff"
                opacity: 0.25
                visible: root.hasImage
            }

            // ── Spielfeldmarkierungen ─────────────────────────────────
            //  NUR ohne Hintergrundbild: ist ein Foto des Feldes hinterlegt,
            //  sind Tore und Mittelkreis dort schon drauf, und eigene
            //  Markierungen daneben wären doppelt und verschoben.
            Canvas {
                id: grid
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()

                    var step = Math.max(5, root.gridStepCm)
                    var fx, fy

                    // ── Raster, dezent: Ablesehilfe, nicht Motiv ─────────
                    //  Bei unplausibel vielen Linien lieber gar keine, sonst
                    //  wird daraus eine Flaeche.
                    if (root.fieldXCm / step <= 40 && root.fieldYCm / step <= 40) {
                        ctx.strokeStyle = "rgba(120,170,230,0.20)"
                        ctx.lineWidth = 1
                        ctx.setLineDash([2, 5])
                        for (fx = 0; fx <= root.fieldXCm + 1e-6; fx += step) {
                            var px = fieldBox.xToPx(fx)
                            ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, height); ctx.stroke()
                        }
                        for (fy = 0; fy <= root.fieldYCm + 1e-6; fy += step) {
                            var py = fieldBox.yToPx(fy)
                            ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(width, py); ctx.stroke()
                        }
                    }

                    if (root.hasImage)
                        return

                    var line = "rgba(200,225,255,0.80)"
                    ctx.strokeStyle = line
                    ctx.setLineDash([])
                    ctx.lineWidth = 1.6

                    // Mittellinie quer zur langen Achse + Mittelkreis
                    var mx = fieldBox.xToPx(root.fieldXCm / 2)
                    var my = fieldBox.yToPx(root.fieldYCm / 2)
                    ctx.beginPath(); ctx.moveTo(mx, 0); ctx.lineTo(mx, height); ctx.stroke()

                    var rC = Math.max(6, root.centerCircleCm / 2 * fieldBox._cmScale)
                    ctx.beginPath(); ctx.arc(mx, my, rC, 0, 2 * Math.PI); ctx.stroke()
                    ctx.beginPath(); ctx.arc(mx, my, 2.5, 0, 2 * Math.PI)
                    ctx.fillStyle = line; ctx.fill()

                    // ── Tore links und rechts, als Nische nach innen ─────
                    var gd = Math.max(4, root.goalDepthCm * fieldBox._cmScale)
                    var gTop = fieldBox.yToPx((root.fieldYCm + root.goalWidthCm) / 2)
                    var gBot = fieldBox.yToPx((root.fieldYCm - root.goalWidthCm) / 2)

                    function goal(x0, x1) {
                        var left = Math.min(x0, x1)
                        ctx.fillStyle = "rgba(120,180,240,0.22)"
                        ctx.fillRect(left, gTop, Math.abs(x1 - x0), gBot - gTop)
                        ctx.strokeStyle = line
                        ctx.lineWidth = 2
                        ctx.strokeRect(left + 1, gTop + 1,
                                       Math.abs(x1 - x0) - 2, gBot - gTop - 2)
                        if (gBot - gTop > 34) {
                            ctx.save()
                            ctx.translate((x0 + x1) / 2, (gTop + gBot) / 2)
                            ctx.rotate(-Math.PI / 2)
                            ctx.fillStyle = line
                            ctx.font = "bold 11px sans-serif"
                            ctx.textAlign = "center"
                            ctx.textBaseline = "middle"
                            ctx.fillText("TOR", 0, 0)
                            ctx.restore()
                        }
                    }
                    goal(0, gd)                    // x = 0
                    goal(width, width - gd)        // x = fieldXCm
                }
                Component.onCompleted: requestPaint()
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                Connections {
                    target: root
                    function onFieldXCmChanged() { grid.requestPaint() }
                    function onFieldYCmChanged() { grid.requestPaint() }
                    function onGridStepCmChanged() { grid.requestPaint() }
                    function onGoalWidthCmChanged() { grid.requestPaint() }
                    function onGoalDepthCmChanged() { grid.requestPaint() }
                    function onCenterCircleCmChanged() { grid.requestPaint() }
                    function onHasImageChanged() { grid.requestPaint() }
                }
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

            // ── Achsenbeschriftung ────────────────────────────────────
            Text {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 4
                text: "x ►"
                color: Theme.textDim
                font.bold: true
                font.pixelSize: Theme.fontSizeSmall
            }
            Text {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 4
                anchors.topMargin: 20
                text: "▲ y"
                color: Theme.textDim
                font.bold: true
                font.pixelSize: Theme.fontSizeSmall
            }
            Text {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 4
                // Reihenfolge wie im Bild: waagerecht × senkrecht.
                text: root.fieldXCm.toFixed(0) + " × " + root.fieldYCm.toFixed(0) + " cm"
                color: Theme.textDim
                font.pixelSize: Theme.fontSizeSmall
            }

            Repeater {
                model: [root.body1, root.body2]
                delegate: Item {
                    required property var modelData
                    readonly property real bx: fieldBox.xToPx(modelData.x)
                    readonly property real by: fieldBox.yToPx(modelData.y)
                    readonly property real rPx: Math.max(6, Math.abs(modelData.diameter) / 2
                                                             * fieldBox._cmScale)

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

                    // Richtungspfeil. 0 Grad = nach rechts, positiv im
                    // Uhrzeigersinn — QML dreht genauso, siehe Kopfkommentar.
                    Item {
                        anchors.centerIn: parent
                        width: parent.width; height: parent.height
                        rotation: modelData.angleDeg
                        Behavior on rotation {
                            RotationAnimation { duration: 100; direction: RotationAnimation.Shortest }
                        }

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

                    // Beschriftung über dem Körper (mit Hintergrund für Lesbarkeit)
                    Rectangle {
                        anchors.bottom: parent.top
                        anchors.bottomMargin: 4
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: lbl.implicitWidth + 10
                        height: lbl.implicitHeight + 4
                        radius: 2
                        color: Theme.dark ? "#000000" : "#ffffff"
                        opacity: 0.65
                    }
                    Text {
                        id: lbl
                        anchors.bottom: parent.top
                        anchors.bottomMargin: 6
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: modelData.label + "  " + modelData.x.toFixed(0) + "/"
                              + modelData.y.toFixed(0) + " cm  "
                              + modelData.angleDeg.toFixed(0) + "°"
                        color: modelData.color
                        font.bold: true
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
            }
        }
    }
}
