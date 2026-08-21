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
//      x = 0 … fieldXCm   steigend nach OSTEN
//      y = 0 … fieldYCm   steigend nach NORDEN
//      Ursprung (0,0) = südwestliche Ecke
//
//  Dargestellt wird das Feld um 90 Grad nach Osten gedreht (Querformat),
//  passend zum 13"-Querformat-Touchscreen:
//
//      Bildschirm RECHTS  = Norden  (+y)
//      Bildschirm UNTEN   = Osten   (+x)
//
//                       N (+y) ──────────────►
//                    ┌───────────────────────────┐
//        O (+x)  │   │ (0,0)                     │
//                │   │            Feld           │
//                ▼   │                           │
//                    └───────────────────────────┘
//
//  Der Blickwinkel eines Körpers ist ein KOMPASSKURS: 0° = Norden, im
//  Uhrzeigersinn steigend. In genau dieser Darstellung entspricht das
//  unmittelbar der Bildschirmrotation (QML: 0° = nach rechts = Norden,
//  positiv = im Uhrzeigersinn) — es ist also keine Umrechnung nötig.
//
//  Das Feld wird NIE verzerrt gestreckt: das Seitenverhältnis ergibt sich
//  aus fieldYCm : fieldXCm, der Rest bleibt Rand ("Letterboxing").
Item {
    id: root
    implicitWidth: 400
    implicitHeight: 300

    property string label: ""
    property string imageUrl: ""

    // Feldmaße in cm. Standard = RoboCup Junior Soccer Lightweight.
    property real fieldXCm: 180     // Ost-Achse
    property real fieldYCm: 240     // Nord-Achse

    // Rasterabstand in cm.
    property real gridStepCm: 30

    // { label, color, diameter (cm), x (cm, Ost), y (cm, Nord), angleDeg (Kompass) }
    property var body1: ({ label: "", color: "#4ec9b0", diameter: 7,  x: 0, y: 0, angleDeg: 0 })
    property var body2: ({ label: "", color: "#f0c060", diameter: 18, x: 0, y: 0, angleDeg: 0 })

    // Breite:Höhe der Darstellung — Nord liegt waagerecht, Ost senkrecht.
    readonly property real displayAspect: (fieldXCm > 0 ? fieldYCm / fieldXCm : 4 / 3)

    Item {
        id: fieldBox
        readonly property real _byHeightW: root.height * root.displayAspect
        readonly property real _fitsWidth: _byHeightW <= root.width
        width: _fitsWidth ? _byHeightW : root.width
        height: _fitsWidth ? root.height : root.width / root.displayAspect
        anchors.centerIn: parent

        // Feldkoordinaten -> Pixel. Die Drehung um 90 Grad steckt genau hier:
        // die NORD-Koordinate bestimmt die waagerechte, die OST-Koordinate die
        // senkrechte Bildschirmposition.
        function northToPx(fy) { return (fy / Math.max(1, root.fieldYCm)) * width }
        function eastToPx(fx)  { return (fx / Math.max(1, root.fieldXCm)) * height }

        // cm -> Pixel für Durchmesser (beide Achsen sind gleich skaliert,
        // solange das Seitenverhältnis stimmt — der kleinere Wert ist die
        // sichere Wahl).
        readonly property real _cmScale: Math.min(width / Math.max(1, root.fieldYCm),
                                                   height / Math.max(1, root.fieldXCm))

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
            Rectangle {
                anchors.fill: parent
                color: Theme.dark ? "#000000" : "#ffffff"
                opacity: 0.35
                visible: root.imageUrl.length > 0
            }

            // ── Rasterlinien alle gridStepCm ──────────────────────────
            Canvas {
                id: grid
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = "rgba(60,120,200,0.35)"
                    ctx.lineWidth = 1
                    ctx.setLineDash([2, 4])

                    var step = Math.max(5, root.gridStepCm)

                    // Senkrechte Linien = feste Nord-Koordinaten
                    for (var fy = 0; fy <= root.fieldYCm + 1e-6; fy += step) {
                        var px = fieldBox.northToPx(fy)
                        ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, height); ctx.stroke()
                    }
                    // Waagerechte Linien = feste Ost-Koordinaten
                    for (var fx = 0; fx <= root.fieldXCm + 1e-6; fx += step) {
                        var py = fieldBox.eastToPx(fx)
                        ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(width, py); ctx.stroke()
                    }

                    // Mittellinien kräftiger
                    ctx.strokeStyle = "rgba(80,160,255,0.55)"
                    ctx.setLineDash([])
                    ctx.lineWidth = 1.2
                    var mx = fieldBox.northToPx(root.fieldYCm / 2)
                    var my = fieldBox.eastToPx(root.fieldXCm / 2)
                    ctx.beginPath(); ctx.moveTo(mx, 0); ctx.lineTo(mx, height); ctx.stroke()
                    ctx.beginPath(); ctx.moveTo(0, my); ctx.lineTo(width, my); ctx.stroke()
                }
                Component.onCompleted: requestPaint()
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                Connections {
                    target: root
                    function onFieldXCmChanged() { grid.requestPaint() }
                    function onFieldYCmChanged() { grid.requestPaint() }
                    function onGridStepCmChanged() { grid.requestPaint() }
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

            // ── Achsenbeschriftung: ohne die ist die 90-Grad-Drehung
            //    beim ersten Hinsehen nicht zu erkennen. ────────────────
            Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 4
                text: "N ►"
                color: Theme.textDim
                font.bold: true
                font.pixelSize: Theme.fontSizeSmall
            }
            Text {
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottomMargin: 2
                text: "▼ O"
                color: Theme.textDim
                font.bold: true
                font.pixelSize: Theme.fontSizeSmall
            }
            Text {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 4
                text: root.fieldXCm.toFixed(0) + " × " + root.fieldYCm.toFixed(0) + " cm"
                color: Theme.textDim
                font.pixelSize: Theme.fontSizeSmall
            }

            Repeater {
                model: [root.body1, root.body2]
                delegate: Item {
                    required property var modelData
                    readonly property real bx: fieldBox.northToPx(modelData.y)
                    readonly property real by: fieldBox.eastToPx(modelData.x)
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

                    // Richtungspfeil. Kompasskurs = Bildschirmrotation,
                    // siehe Kopfkommentar.
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
