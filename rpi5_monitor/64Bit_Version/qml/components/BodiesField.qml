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

    // Bewegungsspur: trailLength Punkte, jeder trailEvery-te Wert — bei
    // 25 Werten/s also gut zwei Sekunden Weg.
    property bool showTrail: true
    property int trailLength: 20
    property int trailEvery: 3

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
                opacity: 0.15
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
                        // Ueber einem Foto muss das Raster deutlich kraeftiger
                        // sein: ein blasses Blau auf hellgruenem Rasen ist zwar
                        // gezeichnet, aber nicht zu sehen -- es wirkt, als laege
                        // es hinter dem Bild.
                        ctx.strokeStyle = root.hasImage ? "rgba(255,255,255,0.55)"
                                                        : "rgba(120,170,230,0.25)"
                        ctx.lineWidth = root.hasImage ? 1.3 : 1
                        ctx.setLineDash([3, 4])
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

            // ── Ein Körper: Spur + Kreis + Richtungspfeil + Beschriftung ──
            //
            //  Ungültige Werte (NaN, Unendlich, der Füllwert 9898 für nicht
            //  belegte Kanäle) blenden den Körper aus, statt ihn irgendwohin
            //  zu zeichnen. Werte außerhalb des Feldes — typisch für "Ball
            //  nicht gesehen" = -1 — landen am Feldrand, blass und mit dem
            //  Hinweis "außerhalb", damit man sieht, dass etwas kommt, aber
            //  nicht glaubt, der Ball läge im Aus.
            component BodyLayer: Item {
                id: body
                anchors.fill: parent
                property var bodyData

                function _num(v) { return typeof v === "number" && isFinite(v) && v !== 9898 }

                readonly property bool hasPos: !!bodyData && bodyData.label !== ""
                                               && _num(bodyData.x) && _num(bodyData.y)
                readonly property bool hasAngle: hasPos && _num(bodyData.angleDeg)
                readonly property real fx: hasPos ? Math.max(0, Math.min(root.fieldXCm, bodyData.x)) : 0
                readonly property real fy: hasPos ? Math.max(0, Math.min(root.fieldYCm, bodyData.y)) : 0
                readonly property bool outside: hasPos && (fx !== bodyData.x || fy !== bodyData.y)
                readonly property color col: bodyData ? bodyData.color : "#ffffff"

                // ── Spur der letzten gut zwei Sekunden ─────────────────────
                //  Fester Pool aus Punkten statt eines Modells, das sich mit
                //  jedem Wert ändert: ein Repeater mit wechselndem Modell baut
                //  bei jeder Änderung ALLE Delegates neu auf. So verschieben
                //  sich nur Punkte, und es kommt keine Abhängigkeit (Shapes)
                //  hinzu, die auf dem Pi extra installiert werden müsste.
                property var trail: []
                property int _tick: 0
                onBodyDataChanged: {
                    if (!root.showTrail || !hasPos || outside)
                        return
                    _tick = (_tick + 1) % root.trailEvery
                    if (_tick !== 0)
                        return
                    var t = trail.length >= root.trailLength
                            ? trail.slice(trail.length - root.trailLength + 1) : trail.slice()
                    t.push(Qt.point(fx, fy))
                    trail = t
                }
                Connections {
                    target: root
                    function onShowTrailChanged() { body.trail = [] }
                }

                Repeater {
                    model: root.showTrail ? root.trailLength : 0
                    Rectangle {
                        readonly property var p: index < body.trail.length ? body.trail[index] : null
                        visible: p !== null && body.hasPos
                        width: 4; height: 4; radius: 2
                        x: p ? fieldBox.xToPx(p.x) - 2 : 0
                        y: p ? fieldBox.yToPx(p.y) - 2 : 0
                        color: body.col
                        // älter = blasser
                        opacity: 0.15 + 0.6 * (index + 1) / Math.max(1, body.trail.length)
                    }
                }

                Item {
                    id: bodyDelegate
                    visible: body.hasPos
                    opacity: body.outside ? 0.45 : 1.0
                    readonly property real bx: fieldBox.xToPx(body.fx)
                    readonly property real by: fieldBox.yToPx(body.fy)
                    readonly property real rPx: Math.max(6, Math.abs(body.bodyData && body._num(body.bodyData.diameter)
                                                                     ? body.bodyData.diameter : 0) / 2
                                                             * fieldBox._cmScale)
                    x: bx - rPx; y: by - rPx
                    width: rPx * 2; height: rPx * 2

                    // Glow
                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.width + 16; height: parent.height + 16
                        radius: width / 2
                        color: body.col
                        opacity: 0.18
                    }

                    // Körper
                    Rectangle {
                        anchors.fill: parent
                        radius: width / 2
                        color: body.col
                        opacity: 0.72
                        border.color: body.col
                        border.width: 2.5
                    }

                    // Richtungspfeil. 0 Grad = nach rechts, positiv im Uhrzeigersinn
                    Item {
                        visible: body.hasAngle
                        anchors.centerIn: parent
                        width: parent.width; height: parent.height
                        rotation: body.hasAngle ? body.bodyData.angleDeg : 0

                        Rectangle {
                            width: Math.max(14, parent.width * 0.9)
                            height: 3
                            radius: 1.5
                            color: body.col
                            x: parent.width / 2
                            y: parent.height / 2 - height / 2
                        }
                        Rectangle {
                            width: 10; height: 10
                            rotation: 45
                            color: body.col
                            x: parent.width / 2 + Math.max(14, parent.width * 0.9) - 5
                            y: parent.height / 2 - 5
                        }
                    }

                    // Beschriftung über dem Körper — am oberen Feldrand
                    // darunter, sonst schneidet der Rahmen sie ab.
                    readonly property bool labelBelow: by - rPx < bodyLbl.implicitHeight + 10
                    Rectangle {
                        anchors.centerIn: bodyLbl
                        width: bodyLbl.implicitWidth + 10
                        height: bodyLbl.implicitHeight + 4
                        radius: 2
                        color: Theme.dark ? "#000000" : "#ffffff"
                        opacity: 0.65
                    }
                    Text {
                        id: bodyLbl
                        // Mittig über dem Körper, aber nie über den Feldrand
                        // hinaus (sonst schneidet der Rahmen sie ab).
                        x: Math.max(6 - bodyDelegate.x,
                                    Math.min(fieldBox.width - implicitWidth - 6 - bodyDelegate.x,
                                             (parent.width - implicitWidth) / 2))
                        y: bodyDelegate.labelBelow ? parent.height + 6 : -implicitHeight - 6
                        text: !body.hasPos ? ""
                              : body.bodyData.label + "  " + body.bodyData.x.toFixed(0) + "/"
                                + body.bodyData.y.toFixed(0) + " cm"
                                + (body.hasAngle ? "  " + body.bodyData.angleDeg.toFixed(0) + "°" : "")
                                + (body.outside ? "  (außerhalb)" : "")
                        color: body.col
                        font.bold: true
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
            }

            BodyLayer { bodyData: root.body1 }
            BodyLayer { bodyData: root.body2 }

            // ── Spur ein/aus ──────────────────────────────────────────
            Rectangle {
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: 6
                width: trailLbl.implicitWidth + 16
                height: trailLbl.implicitHeight + 8
                radius: Theme.radiusS
                color: root.showTrail ? Theme.accentBlue : (Theme.dark ? "#000000" : "#ffffff")
                opacity: 0.8
                Text {
                    id: trailLbl
                    anchors.centerIn: parent
                    text: "Spur"
                    color: root.showTrail ? "#ffffff" : Theme.textDim
                    font.bold: true
                    font.pixelSize: Theme.fontSizeSmall
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: root.showTrail = !root.showTrail
                }
            }
        }
    }
}
