import QtQuick
import QtQuick.Controls
import App
import "components"

// Migrationsplan Abschnitt 4.3. TableView statt QTableView, gespeist vom
// TelemetryTableModel. Der Suchfilter wird im MODELL ausgewertet
// (telemetry.setFilter) und nicht über `visible: false` im Delegate — eine
// TableView reserviert die Höhe unsichtbarer Zeilen weiterhin, die gefilterte
// Liste bestand vorher deshalb überwiegend aus Lücken.
Item {
    id: root
    property var telemetry: appBridge.telemetry

    // Die Tabelle nur auffrischen, solange dieser Tab vorn ist (siehe
    // TelemetryTableModel.set_live). Min/Max laufen im Modell weiter.
    readonly property bool pageActive: SwipeView.view ? SwipeView.isCurrentItem : true
    onPageActiveChanged: telemetry.setTableLive(pageActive)
    Component.onCompleted: telemetry.setTableLive(pageActive)

    // Min/Max/Delta sind leer, solange ein Kanal noch keinen endlichen Wert
    // hatte (TelemetryTableModel gibt dann None zurueck). In QML kommt das als
    // `undefined` an, NICHT als `null` — die fruehere Abfrage `!== null` war
    // deshalb immer wahr und lief in `undefined.toFixed()`. Ergebnis: bei jedem
    // ungenutzten Kanal blieben die drei Spalten leer statt "—" zu zeigen.
    function fmt(v, digits) {
        return (typeof v === "number" && isFinite(v)) ? v.toFixed(digits) : "—"
    }

    // ── Spaltenbreiten ───────────────────────────────────────────────────
    //  Alle Breiten wachsen mit der Schriftgroesse. Vorher waren es feste
    //  Pixel: bei 140 % Schrift passte "-123.4567" nicht mehr in 90 px und
    //  lief in die Einheit. Der Name bekommt, was uebrig bleibt — auf einem
    //  breiten Display wurden lange Kanalnamen sonst bei 160 px abgeschnitten,
    //  waehrend rechts die halbe Zeile leer stand.
    readonly property real _s: Theme.fontScale
    readonly property int rowPad: Theme.spacingS
    readonly property int colGap: Theme.spacingM
    readonly property int colChannel: Math.round(36 * _s)
    readonly property int colValue: Math.round(118 * _s)
    readonly property int colUnit: Math.round(52 * _s)
    readonly property int colStat: Math.round(96 * _s)
    readonly property int colName: Math.max(Math.round(90 * _s),
        width - 2 * Theme.spacingS - 2 * rowPad - 6 * colGap
        - colChannel - colValue - colUnit - 3 * colStat)

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingS
        spacing: Theme.spacingS

        Row {
            id: toolbar
            width: parent.width
            spacing: Theme.spacingS

            TextField {
                id: filterField
                width: parent.width - resetBtn.width - Theme.spacingS
                height: resetBtn.height
                placeholderText: "Filter (Name oder Kanalnummer)…"
                color: Theme.text
                background: Rectangle {
                    color: Theme.bgInput
                    radius: Theme.radiusS
                    border.color: filterField.activeFocus ? Theme.highlight : Theme.border
                }
                // Entprellt: bei jedem Tastendruck das Modell zurückzusetzen
                // würde auf dem RPi sichtbar ruckeln.
                onTextChanged: filterDebounce.restart()
                Timer {
                    id: filterDebounce
                    interval: 150
                    onTriggered: root.telemetry.setFilter(filterField.text)
                }
            }

            AppButton {
                id: resetBtn
                text: "Min/Max zurücksetzen"
                onClicked: root.telemetry.clear_stats()
            }
        }

        Text {
            id: countLabel
            text: root.telemetry.visibleChannels === root.telemetry.activeChannels
                  ? "Aktive Kanäle: " + root.telemetry.activeChannels
                  : root.telemetry.visibleChannels + " von " +
                    root.telemetry.activeChannels + " Kanälen (gefiltert)"
            color: Theme.accentGreen
            font.pixelSize: Theme.fontSizeSmall
        }

        // ── Spaltenkoepfe ────────────────────────────────────────────────
        //  Eine Zeile mit denselben Breiten wie die Datenzeilen (root.col*).
        //  Vorher stand "min"/"max"/"Δ" in JEDER Zeile vor der Zahl — das
        //  kostete Platz und machte die Zahlen untereinander unruhig.
        Rectangle {
            id: headerRow
            width: parent.width
            height: Math.round(28 * Theme.fontScale)
            radius: Theme.radiusS
            color: Theme.bgMid

            Row {
                anchors.fill: parent
                anchors.leftMargin: root.rowPad
                anchors.rightMargin: root.rowPad
                spacing: root.colGap

                Repeater {
                    model: [
                        { t: "#",       w: root.colChannel, right: true },
                        { t: "Name",    w: root.colName,    right: false },
                        { t: "Wert",    w: root.colValue,   right: true },
                        { t: "Einheit", w: root.colUnit,    right: false },
                        { t: "Min",     w: root.colStat,    right: true },
                        { t: "Max",     w: root.colStat,    right: true },
                        { t: "Δ",       w: root.colStat,    right: true }
                    ]
                    delegate: Text {
                        required property var modelData
                        width: modelData.w
                        anchors.verticalCenter: parent.verticalCenter
                        horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                        elide: Text.ElideRight
                        text: modelData.t
                        color: Theme.textDim
                        font.bold: true
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
            }
        }

        Item {
            width: parent.width
            height: Math.max(0, parent.height - toolbar.height - countLabel.height
                                - headerRow.height - Theme.spacingS * 3)

            TableView {
                id: table
                anchors.fill: parent
                clip: true
                model: telemetryModel
                columnSpacing: 0
                rowSpacing: 0
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true

                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                    required property int row
                    required property string varName
                    required property real current
                    required property var minVal
                    required property var maxVal
                    required property var delta
                    required property string unit
                    required property int channel

                    implicitWidth: table.width
                    implicitHeight: Math.round(36 * Theme.fontScale)
                    // Abwechselnd hinterlegt statt jede Zeile dick umrandet: die
                    // Rahmen waren das Auffaelligste an der Tabelle, nicht die Werte.
                    color: row % 2 === 0 ? Theme.bg : Theme.bgMid
                    radius: Theme.radiusS

                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: root.rowPad
                        anchors.rightMargin: root.rowPad
                        spacing: root.colGap

                        Text {
                            text: channel
                            color: Theme.textDim
                            font.family: Theme.fontMono
                            width: root.colChannel
                            horizontalAlignment: Text.AlignRight
                            font.pixelSize: Theme.fontSizeSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: varName
                            color: Theme.textjulius
                            font.family: Theme.fontMono
                            width: root.colName
                            elide: Text.ElideRight
                            font.pixelSize: Theme.fontSizeBase
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        // Wert und Einheit bewusst getrennt: so bleiben die Zahlen
                        // rechtsbuendig untereinander, auch wenn nur ein Teil der
                        // Kanaele eine Einheit hat.
                        Text {
                            text: current.toFixed(4)
                            // Vorzeichenfarbe aus dem Theme. Die frueher vom
                            // Modell gelieferten festen Farben waren fuer das
                            // dunkle Schema gewaehlt — eine 0 stand im hellen
                            // Schema hellgrau auf hellgrau.
                            color: current > 0 ? Theme.accentGreen
                                 : (current < 0 ? Theme.accentRed : Theme.text)
                            font.family: Theme.fontMono
                            font.bold: true
                            width: root.colValue
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideLeft
                            font.pixelSize: Theme.fontSizeBase
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: unit
                            color: Theme.textDim
                            font.family: Theme.fontMono
                            width: root.colUnit
                            elide: Text.ElideRight
                            font.pixelSize: Theme.fontSizeSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: root.fmt(minVal, 3)
                            color: Theme.textDim
                            font.family: Theme.fontMono
                            width: root.colStat
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideLeft
                            font.pixelSize: Theme.fontSizeSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: root.fmt(maxVal, 3)
                            color: Theme.textDim
                            font.family: Theme.fontMono
                            width: root.colStat
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideLeft
                            font.pixelSize: Theme.fontSizeSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: root.fmt(delta, 3)
                            color: Theme.textDim
                            font.family: Theme.fontMono
                            width: root.colStat
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideLeft
                            font.pixelSize: Theme.fontSizeSmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }

            // Ohne Daten stand hier eine leere Flaeche — und man wusste
            // nicht, ob die Tabelle kaputt ist oder nur nichts ankommt.
            Text {
                anchors.centerIn: parent
                visible: root.telemetry.visibleChannels === 0
                color: Theme.textDim
                font.pixelSize: Theme.fontSizeBase
                text: root.telemetry.activeChannels === 0
                      ? "Noch keine Telemetrie von Node " + appBridge.activeNode + "."
                      : "Kein Kanal passt zum Filter."
            }
        }
    }
}
