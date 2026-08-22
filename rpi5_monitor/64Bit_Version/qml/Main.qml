import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Controls.Material
import App
import "components"

// Ersatz für main_window.py::MainWindow.
// SwipeView statt QTabWidget: erlaubt Wischen zwischen Tabs (Touch-
// Standardpattern), TabBar bleibt zusätzlich als Schnellzugriff/Indikator.
ApplicationWindow {
    id: window
    visible: true
    width: 1280
    height: 800
    title: "Power Debug Monitor"
    // 13"-Touchscreen-Kiosk-Betrieb: startet direkt im Vollbild statt in
    // einem verschiebbaren Fenster.
    visibility: Window.FullScreen

    Material.theme: Theme.dark ? Material.Dark : Material.Light
    Material.accent: Theme.highlight
    Material.background: Theme.bg
    Material.foreground: Theme.text
    color: Theme.bg
    font.pixelSize: Theme.fontSizeBase

    // ── Tastatursteuerung (B4) ───────────────────────────────────────────
    //  W/S vorwärts/rückwärts, A/D seitwärts, Q/E drehen, Shift schneller,
    //  R/F Dribbler, Leertaste Not-Aus.
    //
    //  Warum ein eigenes Item mit einem Bitfeld statt einzelner Booleans:
    //  Qt liefert bei gehaltener Taste automatische Wiederholungen. Würde
    //  jede davon einen Zustand setzen, käme beim Loslassen ZWEIER Tasten
    //  die falsche Reihenfolge heraus. Mit einem Bitfeld ist der Zustand
    //  immer die Summe aller wirklich gehaltenen Tasten.
    QtObject {
        id: keys
        property int held: 0
        readonly property int kW: 1
        readonly property int kA: 2
        readonly property int kS: 4
        readonly property int kD: 8
        readonly property int kQ: 16
        readonly property int kE: 32
        readonly property int kShift: 64
        readonly property int kR: 128
        readonly property int kF: 256

        function bit(key) {
            switch (key) {
                case Qt.Key_W: return kW
                case Qt.Key_A: return kA
                case Qt.Key_S: return kS
                case Qt.Key_D: return kD
                case Qt.Key_Q: return kQ
                case Qt.Key_E: return kE
                case Qt.Key_Shift: return kShift
                case Qt.Key_R: return kR
                case Qt.Key_F: return kF
            }
            return 0
        }

        function push() {
            var x = ((held & kD) ? 1 : 0) - ((held & kA) ? 1 : 0)
            var y = ((held & kW) ? 1 : 0) - ((held & kS) ? 1 : 0)
            var rot = ((held & kE) ? 1 : 0) - ((held & kQ) ? 1 : 0)
            var moving = (x !== 0 || y !== 0 || rot !== 0)
            // Ohne gedrückte Richtungstaste bleibt der Gasstand 0 — sonst
            // würde ein bloßes Shift den Roboter losfahren lassen.
            var speed = moving ? ((held & kShift) ? 1.0 : 0.5) : 0.0
            var dribbler = ((held & kR) ? 1 : 0) - ((held & kF) ? 1 : 0)
            appBridge.params.setKeyboardAxes(x, y, rot, speed, dribbler)
        }
    }

    // Der Auffaenger UMSCHLIESST die Ansichten. Tasten-Ereignisse steigen in
    // QML nur den ELTERN-Pfad des fokussierten Elements hoch — als Geschwister
    // der SwipeView haette er nie etwas gesehen, sobald irgendein Bedienelement
    // den Fokus hat. So bleibt ausserdem das erwuenschte Verhalten erhalten,
    // dass ein Textfeld die Buchstaben zuerst bekommt und WASD dort ganz
    // normal getippt werden kann.
    Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.onPressed: (event) => {
            if (event.isAutoRepeat) { event.accepted = false; return }
            if (event.key === Qt.Key_Space) {
                appBridge.params.stopAll()
                keys.held = 0
                event.accepted = true
                return
            }
            var b = keys.bit(event.key)
            if (b === 0 || !appBridge.settings.keyboardControl) { event.accepted = false; return }
            keys.held |= b
            keys.push()
            event.accepted = true
        }
        Keys.onReleased: (event) => {
            if (event.isAutoRepeat) { event.accepted = false; return }
            var b = keys.bit(event.key)
            if (b === 0) { event.accepted = false; return }
            keys.held &= ~b
            keys.push()
            event.accepted = true
        }

        SwipeView {
            id: swipeView
            anchors.fill: parent
            // Zwei-Wege-Kopplung TabBar <-> SwipeView nach dem Qt-Standardmuster:
            // BEIDE Seiten binden aneinander, es gibt bewusst KEINE zusätzliche
            // imperative Zuweisung mehr. Eine solche Zuweisung auf
            // swipeView.currentIndex hat dessen Binding beim ersten Tab-Wechsel
            // zerstört (klassischer QML-Bindungsschleifen-Fehler).
            currentIndex: tabBar.currentIndex
            // Während ein Touch-Widget wie der Joystick exklusiv einen Drag
            // braucht (siehe UiState.qml / Joystick.qml), darf das Wischen
            // zwischen den Tabs nicht mitlaufen.
            interactive: !UiState.navigationLocked

            TelemetryView {}
            PlotterView {}
            SystemView {}
            ParamsView {}
            DiagnosticsView {}
        }
    }

    // ESC beendet die Anwendung, Strg+S fährt den Raspberry Pi herunter
    // (appBridge.systemShutdown(), siehe bridge/app_bridge.py — auf
    // Nicht-Linux-Systemen beim Testen nur eine Log-Warnung).
    Shortcut {
        sequence: "Esc"
        // Im Kiosk-Modus soll ein versehentlicher Tastendruck am Spielfeldrand
        // die Oberfläche nicht beenden.
        onActivated: if (!appBridge.settings.kiosk) Qt.quit()
    }
    Shortcut {
        sequence: "Ctrl+S"
        onActivated: if (!appBridge.settings.kiosk) appBridge.systemShutdown()
    }
    Shortcut {
        sequence: "Ctrl+D"
        onActivated: appBridge.settings.toggleTheme()
    }
    Shortcut {
        sequence: "Ctrl+Z"
        onActivated: appBridge.params.undo()
    }

    header: Column {
        width: window.width
        spacing: 0

        Rectangle {
            width: parent.width
            height: Math.round(72 * Theme.fontScale)
            color: Theme.bgMid

            Row {
                anchors.fill: parent
                anchors.margins: Theme.spacingS
                spacing: Theme.spacingM

                NodeSelector {
                    width: 360
                    height: parent.height
                    activeNode: appBridge.activeNode
                    node1Connected: appBridge.node1Connected
                    node2Connected: appBridge.node2Connected
                    node1Ip: appBridge.node1Ip
                    node2Ip: appBridge.node2Ip
                    onNodeSelected: (nodeId) => appBridge.setActiveNode(nodeId)
                }

                // Kein Not-Aus-Knopf in der Kopfzeile (auf Wunsch entfernt).
                // Der Not-Aus liegt weiterhin auf der LEERTASTE, siehe
                // keyCatcher weiter oben — der ist am Spielfeldrand ohnehin
                // schneller zu treffen als ein Ziel auf dem Touchscreen.
                AppButton {
                    width: 150
                    height: parent.height
                    text: "🏷 Kanalnamen"
                    onClicked: appBridge.requestChannelNames()
                }

                TabBar {
                    id: tabBar
                    width: parent.width - 360 - 150 - Theme.spacingM * 2
                    height: parent.height
                    currentIndex: swipeView.currentIndex
                    Material.background: "transparent"

                    TabButton { text: "Tabelle" }
                    TabButton { text: "Plotter" }
                    TabButton { text: "Systemansicht" }
                    TabButton { text: "Parameter" }
                    TabButton {
                        text: appBridge.diag.errorCount > 0
                              ? "Diagnose (" + appBridge.diag.errorCount + ")"
                              : "Diagnose"
                    }
                }
            }
        }
    }

    // appBridge.statusText trägt die letzte Meldung (Node gewechselt,
    // Kanalnamen angefordert, Empfänger neu gestartet, ...).
    footer: StatusBar {
        pps: appBridge.packetsPerSecond
        message: appBridge.statusText
        anyNodeConnected: appBridge.node1Connected || appBridge.node2Connected
        firmware: appBridge.firmwareText
        alarmLevel: appBridge.diag.alarmLevel
        batteryValue: appBridge.diag.batteryValue
    }


    // ── Akku-Alarm (C3): rein optisch, es wird NICHTS am Roboter verändert ─
    Rectangle {
        id: alarmFrame
        anchors.fill: parent
        color: "transparent"
        visible: appBridge.diag.alarmLevel > 0
        border.width: 6
        border.color: appBridge.diag.alarmLevel >= 2 ? Theme.ledOff : Theme.accentAmber
        z: 1000

        // Klicks müssen durchgehen — der Rahmen ist reine Anzeige.
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: Theme.spacingS
            width: alarmLabel.implicitWidth + 2 * Theme.spacingM
            height: alarmLabel.implicitHeight + Theme.spacingS
            radius: Theme.radiusM
            color: appBridge.diag.alarmLevel >= 2 ? Theme.errorBg : Theme.warnBg
            border.color: alarmFrame.border.color
            Text {
                id: alarmLabel
                anchors.centerIn: parent
                font.bold: true
                font.pixelSize: Theme.fontSizeLarge
                color: alarmFrame.border.color
                text: (appBridge.diag.alarmLevel >= 2 ? "AKKU KRITISCH" : "Akku schwach")
                      + ": " + appBridge.diag.batteryValue.toFixed(2)
            }
        }

        // Blinken ueber eine gebundene Property statt "Animation on opacity":
        // eine Animation UEBERNIMMT die Property, und die Zuweisung beim
        // Anhalten kollidiert damit. Ausserdem bliebe die Deckkraft sonst auf
        // dem zuletzt animierten Wert stehen, wenn der Alarm von kritisch auf
        // Warnung zurueckfaellt.
        property bool blinkOn: true
        opacity: (appBridge.diag.alarmLevel >= 2 && !blinkOn) ? 0.3 : 1.0
        Behavior on opacity { NumberAnimation { duration: 250 } }

        Timer {
            interval: 500
            repeat: true
            running: alarmFrame.visible && appBridge.diag.alarmLevel >= 2
            onTriggered: alarmFrame.blinkOn = !alarmFrame.blinkOn
            onRunningChanged: if (!running) alarmFrame.blinkOn = true
        }
    }
}
