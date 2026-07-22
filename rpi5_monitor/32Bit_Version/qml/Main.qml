import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Controls.Material 2.15
import App 1.0
import "components"

// Migrationsplan Abschnitt 4.2 — Ersatz für main_window.py::MainWindow.
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

    Material.theme: Material.Dark
    Material.accent: Theme.highlight
    Material.background: Theme.bg
    Material.foreground: Theme.text
    color: Theme.bg

    // ESC beendet die Anwendung, Strg+S fährt den Raspberry Pi herunter
    // (appBridge.systemShutdown(), siehe bridge/app_bridge.py — auf
    // Nicht-Linux-Systemen beim Testen nur eine Log-Warnung).
    Shortcut {
        sequence: "Esc"
        onActivated: Qt.quit()
    }
    Shortcut {
        sequence: "Ctrl+S"
        onActivated: appBridge.systemShutdown()
    }

    header: Column {
        width: window.width
        spacing: 0

        Rectangle {
            width: parent.width
            height: 72
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

                TabBar {
                    id: tabBar
                    width: parent.width - 360 - Theme.spacingM
                    height: parent.height
                    currentIndex: swipeView.currentIndex
                    Material.background: "transparent"

                    TabButton { text: "Tabelle" }
                    TabButton { text: "Plotter" }
                    TabButton { text: "Systemansicht" }
                    TabButton { text: "Parameter" }
                }
            }
        }
    }

    footer: StatusBar {
        pps: appBridge.packetsPerSecond
        message: ""
    }

    SwipeView {
        id: swipeView
        anchors.fill: parent
        currentIndex: tabBar.currentIndex
        // Während ein Touch-Widget wie der Joystick exklusiv einen Drag
        // braucht (siehe UiState.qml / Joystick.qml), darf das Wischen
        // zwischen den Tabs nicht mitlaufen.
        interactive: !UiState.navigationLocked

        TelemetryView {}
        PlotterView {}
        SystemView {}
        ParamsView {}
    }

    Connections {
        target: tabBar
        function onCurrentIndexChanged() { swipeView.currentIndex = tabBar.currentIndex }
    }
}
