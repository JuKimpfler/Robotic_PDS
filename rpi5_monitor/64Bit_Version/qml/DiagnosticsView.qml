import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import App
import "components"

// Tab "Diagnose" — alles, was Zustand statt Messwert ist:
// Verbindungsqualität (C1), Node-Systemstatus (C2), Einstellungen der
// Oberfläche (F7 + Akku-Warnung C3) und das Logbuch (A4/D2).
//
// Bewusst EINE scrollbare Seite mit Abschnitten statt weiterer Unter-Tabs:
// am Spielfeldrand will man den Zustand auf einen Blick, nicht durch drei
// Ebenen navigieren.
Item {
    id: root
    property var diag: appBridge.diag
    property var settings: appBridge.settings

    // "—" statt eines Sentinels, wenn der Systemwert nicht lesbar war
    // (siehe diag_bridge._num).
    function fmt(value, digits, suffix) {
        if (value <= -998) return "—"
        return value.toFixed(digits) + (suffix ? " " + suffix : "")
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: root.width - Theme.spacingM * 2
            spacing: Theme.spacingM

            // ══════════════════════════════════════════════════════════════
            //  C1 — Verbindungsqualität
            // ══════════════════════════════════════════════════════════════
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: linkCol.implicitHeight + Theme.spacingM * 2
                radius: Theme.radiusM
                color: Theme.bgMid
                border.color: Theme.border

                ColumnLayout {
                    id: linkCol
                    anchors.fill: parent
                    anchors.margins: Theme.spacingM
                    spacing: Theme.spacingS

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "Verbindung"
                            color: Theme.accentBlue
                            font.bold: true
                            font.pixelSize: Theme.fontSizeLarge
                        }
                        Item { Layout.fillWidth: true }
                        AppButton {
                            text: "Zähler zurücksetzen"
                            onClicked: root.diag.resetLinkStats()
                        }
                    }

                    Repeater {
                        model: root.diag.linkStats
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            implicitHeight: Theme.touchTargetMin
                            radius: Theme.radiusS
                            color: modelData.active ? Theme.bgAlt : "transparent"
                            border.color: modelData.active ? Theme.highlight : "transparent"

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.spacingS
                                anchors.rightMargin: Theme.spacingS
                                spacing: Theme.spacingL

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 90
                                    text: "Node " + modelData.node
                                    color: Theme.text
                                    font.bold: modelData.active
                                    font.pixelSize: Theme.fontSizeBase
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 120
                                    font.family: Theme.fontMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: modelData.pps > 0 ? Theme.accentGreen : Theme.textDim
                                    text: modelData.pps + " Pkt/s"
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 150
                                    font.family: Theme.fontMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: modelData.lossPercent > 2 ? Theme.accentRed
                                         : (modelData.lossPercent > 0.2 ? Theme.accentAmber
                                                                        : Theme.textDim)
                                    text: "Verlust " + modelData.lossPercent.toFixed(2) + " %"
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 130
                                    font.family: Theme.fontMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.textDim
                                    text: modelData.rttMs < 0
                                          ? "Ping —"
                                          : "Ping " + modelData.rttMs.toFixed(0) + " ms"
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    font.family: Theme.fontMono
                                    font.pixelSize: Theme.fontSizeSmall
                                    color: Theme.accentBlue
                                    text: modelData.firmware
                                }
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSizeSmall
                        text: "Der Verlust wird aus den Zeitstempeln des Teensy geschätzt: "
                              + "er sendet exakt alle 10 ms, jede größere Lücke sind fehlende "
                              + "Pakete. Der Ping misst GUI → Node → GUI."
                    }
                }
            }

            // ══════════════════════════════════════════════════════════════
            //  C2 — Systemzustand der Nodes
            // ══════════════════════════════════════════════════════════════
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: nodeCol.implicitHeight + Theme.spacingM * 2
                radius: Theme.radiusM
                color: Theme.bgMid
                border.color: Theme.border

                ColumnLayout {
                    id: nodeCol
                    anchors.fill: parent
                    anchors.margins: Theme.spacingM
                    spacing: Theme.spacingS

                    Text {
                        text: "Raspberry Pi Zero (Node)"
                        color: Theme.accentBlue
                        font.bold: true
                        font.pixelSize: Theme.fontSizeLarge
                    }

                    Repeater {
                        model: root.diag.nodeStatus
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 2

                            Row {
                                spacing: Theme.spacingS
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 10; height: 10; radius: 5
                                    color: modelData.fresh ? Theme.ledOn : Theme.ledOff
                                }
                                Text {
                                    text: "Node " + modelData.node
                                          + (modelData.fresh ? "" : "  (kein Statuspaket)")
                                    color: Theme.text
                                    font.bold: modelData.active
                                    font.pixelSize: Theme.fontSizeBase
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: modelData.fresh
                                font.family: Theme.fontMono
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.textDim
                                wrapMode: Text.WordWrap
                                text: "CPU " + root.fmt(modelData.cpuTemp, 1, "°C")
                                      + "   Last " + root.fmt(modelData.load1, 2, "")
                                      + "   Speicher " + root.fmt(modelData.memUsedPct, 0, "%")
                                      + "   WLAN " + root.fmt(modelData.rssiDbm, 0, "dBm")
                                      + "   Laufzeit " + modelData.uptimeText
                                      + "   UART " + modelData.uartPackets + " Pkt"
                                      + (modelData.syncLosses > 0
                                         ? " (" + modelData.syncLosses + " Sync-Verluste)" : "")
                                      + (modelData.teensyLink ? "   Teensy ✓" : "   Teensy ✗")
                                      + (modelData.unicast ? "   Unicast" : "   BROADCAST")
                            }
                        }
                    }
                }
            }

            // ══════════════════════════════════════════════════════════════
            //  Einstellungen
            // ══════════════════════════════════════════════════════════════
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: setCol.implicitHeight + Theme.spacingM * 2
                radius: Theme.radiusM
                color: Theme.bgMid
                border.color: Theme.border

                ColumnLayout {
                    id: setCol
                    anchors.fill: parent
                    anchors.margins: Theme.spacingM
                    spacing: Theme.spacingS

                    Text {
                        text: "Einstellungen"
                        color: Theme.accentBlue
                        font.bold: true
                        font.pixelSize: Theme.fontSizeLarge
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.spacingM

                        AppSwitch {
                            text: "Dunkles Farbschema"
                            checked: root.settings.dark
                            onToggled: (v) => root.settings.setDark(v)
                        }
                        AppSwitch {
                            text: "Kiosk-Modus (ESC/Shutdown sperren)"
                            checked: root.settings.kiosk
                            onToggled: (v) => root.settings.setKiosk(v)
                        }
                        AppSwitch {
                            text: "Tastatursteuerung (WASD)"
                            checked: root.settings.keyboardControl
                            onToggled: (v) => root.settings.setKeyboardControl(v)
                        }
                        AppSwitch {
                            text: "Konfiguration vom Teensy übernehmen"
                            checked: root.settings.autoApplyTeensyConfig
                            onToggled: (v) => root.settings.setAutoApplyTeensyConfig(v)
                        }
                        AppSwitch {
                            text: "Aussehen vom Teensy übernehmen"
                            checked: root.settings.autoApplyTeensySettings
                            enabled: root.settings.autoApplyTeensyConfig
                            onToggled: (v) => root.settings.setAutoApplyTeensySettings(v)
                        }

                        Row {
                            spacing: Theme.spacingXs
                            Label {
                                text: "Start-Tab:"
                                color: Theme.text
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            ComboBox {
                                width: 200
                                height: Theme.touchTargetMin
                                // Reihenfolge wie die SwipeView in Main.qml.
                                model: ["Tabelle", "Plotter", "Systemansicht",
                                        "Parameter", "Diagnose"]
                                currentIndex: root.settings.startTab
                                onActivated: (idx) => root.settings.setStartTab(idx)
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacingS
                        Label {
                            text: "Schriftgröße:"
                            color: Theme.text
                        }
                        Slider {
                            id: fontSlider
                            // Grenzen aus settings.json -> "ranges.fontScale"
                            // (siehe app_settings.py). SettingsBridge begrenzt
                            // auf denselben Bereich — der Regler kann also gar
                            // nicht erst irgendwohin zeigen, wo der Wert nicht
                            // hinkommt.
                            readonly property var rng: root.settings.ranges.fontScale
                            Layout.preferredWidth: 260
                            from: rng.min; to: rng.max; stepSize: rng.step
                            value: root.settings.fontScale
                            onMoved: root.settings.setFontScale(value)
                        }
                        Text {
                            text: Math.round(root.settings.fontScale * 100) + " %"
                            color: Theme.textDim
                            font.family: Theme.fontMono
                        }
                    }

                    // ── Akku-Warnung (C3) ────────────────────────────────
                    Text {
                        text: "Akku-Warnung"
                        color: Theme.text
                        font.bold: true
                        font.pixelSize: Theme.fontSizeBase
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.spacingM

                        AppSwitch {
                            text: "aktiv"
                            checked: root.diag.batteryConfig.enabled
                            onToggled: (v) => root.diag.setBatteryConfig({ "enabled": v })
                        }

                        Row {
                            spacing: Theme.spacingXs
                            Label {
                                text: "Kanal:"
                                color: Theme.text
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            SpinBox {
                                // settings.json -> "ranges.batteryChannel";
                                // min ist bewusst -1 = "aus".
                                readonly property var rng: root.settings.ranges.batteryChannel
                                height: Theme.touchTargetMin
                                from: rng.min; to: rng.max; stepSize: rng.step
                                value: root.diag.batteryConfig.channel
                                textFromValue: (v) => v < 0 ? "—" : String(v)
                                onValueModified: root.diag.setBatteryConfig({ "channel": value })
                            }
                        }

                        Row {
                            spacing: Theme.spacingXs
                            Label {
                                text: "Warnung unter:"
                                color: Theme.text
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            TextField {
                                width: 100
                                height: Theme.touchTargetMin
                                text: root.diag.batteryConfig.warn_below.toFixed(2)
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                onEditingFinished: {
                                    var v = parseFloat(text.replace(",", "."))
                                    if (!isNaN(v)) root.diag.setBatteryConfig({ "warn_below": v })
                                }
                            }
                        }

                        Row {
                            spacing: Theme.spacingXs
                            Label {
                                text: "kritisch unter:"
                                color: Theme.text
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            TextField {
                                width: 100
                                height: Theme.touchTargetMin
                                text: root.diag.batteryConfig.critical_below.toFixed(2)
                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                onEditingFinished: {
                                    var v = parseFloat(text.replace(",", "."))
                                    if (!isNaN(v)) root.diag.setBatteryConfig({ "critical_below": v })
                                }
                            }
                        }

                        Row {
                            spacing: Theme.spacingXs
                            Label {
                                text: "Haltezeit:"
                                color: Theme.text
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            SpinBox {
                                // settings.json -> "ranges.batteryHoldSeconds",
                                // dort in SEKUNDEN. Die SpinBox rechnet nur in
                                // ganzen Zahlen, deshalb der Faktor 1/Schritt
                                // (0,1 s -> 10) statt einer festen 10.
                                readonly property var rng: root.settings.ranges.batteryHoldSeconds
                                readonly property real f: 1.0 / rng.step
                                readonly property int digits: Math.max(0, Math.round(Math.log(f) / Math.LN10))
                                height: Theme.touchTargetMin
                                from: Math.round(rng.min * f); to: Math.round(rng.max * f)
                                value: Math.round(root.diag.batteryConfig.hold_seconds * f)
                                textFromValue: (v) => (v / f).toFixed(digits) + " s"
                                onValueModified: root.diag.setBatteryConfig({ "hold_seconds": value / f })
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSizeSmall
                        text: "Rein optisch — es wird nichts am Roboter verändert. Die Haltezeit "
                              + "verhindert Fehlalarme durch die Spannungseinbrüche beim Anfahren."
                    }

                    // ── Einstellungssätze (Profile) ──────────────────────
                    //  Jedes Profil ist eine Datei settings.<Name>.json neben
                    //  main_qml.py (siehe app_settings.py) — also auch von
                    //  Hand kopierbar, ohne die Oberfläche zu bemühen.
                    Text {
                        text: "Einstellungssätze"
                        color: Theme.text
                        font.bold: true
                        font.pixelSize: Theme.fontSizeBase
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Theme.spacingM

                        Row {
                            spacing: Theme.spacingXs
                            ComboBox {
                                id: profileBox
                                width: 220
                                height: Theme.touchTargetMin
                                model: root.settings.profiles
                            }
                            AppButton {
                                text: "Laden"
                                enabled: profileBox.count > 0
                                onClicked: root.settings.loadProfile(profileBox.currentText)
                            }
                            AppButton {
                                text: "Löschen"
                                danger: true
                                enabled: profileBox.count > 0
                                onClicked: root.settings.deleteProfile(profileBox.currentText)
                            }
                        }

                        Row {
                            spacing: Theme.spacingXs
                            TextField {
                                id: profileName
                                width: 220
                                height: Theme.touchTargetMin
                                placeholderText: "Name des Einstellungssatzes"
                            }
                            AppButton {
                                text: "Speichern unter"
                                // Ein leerer Name ergäbe die Datei
                                // "settings..json" — der Knopf bleibt deshalb
                                // grau, statt die Python-Seite ablehnen zu lassen.
                                enabled: profileName.text.trim().length > 0
                                onClicked: root.settings.saveProfile(profileName.text.trim())
                            }
                        }

                        AppButton {
                            text: "Auf Standardwerte zurücksetzen"
                            danger: true
                            onClicked: root.settings.resetToDefaults()
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSizeSmall
                        text: "Alles auf dieser Seite steht in " + root.settings.settingsPath
                              + " — dort lassen sich auch die Grenzen der Regler, Farben und "
                              + "Schriftgrößen ändern. Farben, Maße und Reglergrenzen gelten "
                              + "sofort; Fenstergröße, Netzwerkadressen, Puffergrößen und die "
                              + "Controller-Belegung erst nach einem Neustart."
                    }

                    // ── Gespeicherte Konfiguration ───────────────────────
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacingS
                        AppButton {
                            text: "Gespeicherte Konfiguration verwerfen"
                            danger: true
                            onClicked: appBridge.resetStoredConfig()
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSizeSmall
                            text: appBridge.params.configSource + "   |   "
                                  + appBridge.visuals.configSource
                        }
                    }
                }
            }

            // ══════════════════════════════════════════════════════════════
            //  A4/D2 — Logbuch
            // ══════════════════════════════════════════════════════════════
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(260, root.height * 0.5)
                radius: Theme.radiusM
                color: Theme.bgMid
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingM
                    spacing: Theme.spacingS

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacingS

                        Text {
                            text: "Logbuch (" + root.diag.eventCount + ")"
                            color: Theme.accentBlue
                            font.bold: true
                            font.pixelSize: Theme.fontSizeLarge
                        }
                        Item { Layout.fillWidth: true }

                        ComboBox {
                            width: 190
                            height: Theme.touchTargetMin
                            model: ["alles", "ab Warnung", "nur Fehler"]
                            currentIndex: root.diag.eventFilter
                            onActivated: (idx) => root.diag.setEventFilter(idx)
                        }
                        AppButton {
                            text: "Gelesen"
                            enabled: root.diag.errorCount > 0
                            onClicked: root.diag.acknowledgeErrors()
                        }
                        AppButton {
                            text: "Leeren"
                            onClicked: root.diag.clearEvents()
                        }
                    }

                    ListView {
                        id: eventList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        reuseItems: true
                        model: root.diag.events
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Row {
                            required property var modelData
                            width: eventList.width
                            height: Math.round(24 * Theme.fontScale)
                            spacing: Theme.spacingS

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 78
                                font.family: Theme.fontMono
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.textDim
                                text: modelData.time
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 34
                                font.family: Theme.fontMono
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.textDim
                                text: modelData.node > 0 ? "N" + modelData.node : "GUI"
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 22
                                font.pixelSize: Theme.fontSizeSmall
                                text: modelData.kind === "event" ? "⏱" : "•"
                                color: Theme.textDim
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                font.pixelSize: Theme.fontSizeSmall
                                color: modelData.level >= 2 ? Theme.accentRed
                                     : (modelData.level === 1 ? Theme.accentAmber : Theme.text)
                                text: modelData.text
                                      + (modelData.kind === "event" && modelData.value !== 0
                                         ? "  (" + modelData.value.toFixed(3) + ")" : "")
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: root.diag.eventCount === 0
                        wrapMode: Text.WordWrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSizeSmall
                        text: "Noch keine Meldungen. Im Roboter-Code erzeugen "
                              + "PDS.event(\"…\") eine Marke im Plotter und "
                              + "PDS.log/warn/error(\"…\") eine Zeile hier."
                    }
                }
            }
        }
    }
}
