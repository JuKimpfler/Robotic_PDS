import QtQuick 2.15
import App 1.0

// Ersatz für die QRadioButton-Leiste in main_window.py::_build_control_bar.
// Große Segmented-Control-Buttons (>= Theme.touchTargetMin) statt kleiner
// Radiobuttons + separate LED-Labels je Node.
Rectangle {
    id: root
    implicitHeight: 64
    radius: Theme.radiusM
    color: Theme.bgMid
    border.color: Theme.border

    property int activeNode: 1
    property bool node1Connected: false
    property bool node2Connected: false
    property string node1Ip: ""
    property string node2Ip: ""
    signal nodeSelected(int nodeId)

    Row {
        anchors.fill: parent
        anchors.margins: 6
        spacing: 8

        Repeater {
            model: [
                { id: 1, ip: root.node1Ip, connected: root.node1Connected },
                { id: 2, ip: root.node2Ip, connected: root.node2Connected },
            ]
            delegate: Rectangle {
                required property var modelData
                width: (root.width - 12 - 8) / 2
                height: root.height - 12
                radius: Theme.radiusS
                color: root.activeNode === modelData.id ? Theme.highlight : "transparent"
                border.color: root.activeNode === modelData.id ? Theme.highlight : Theme.border
                border.width: 1

                Row {
                    anchors.centerIn: parent
                    spacing: 10

                    Rectangle {
                        width: 14; height: 14; radius: 7
                        anchors.verticalCenter: parent.verticalCenter
                        color: modelData.connected ? Theme.ledOn : Theme.ledOff
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            text: "Node " + modelData.id
                            color: root.activeNode === modelData.id ? "white" : Theme.text
                            font.pixelSize: Theme.fontSizeBase
                            font.bold: true
                        }
                        Text {
                            text: modelData.ip
                            color: root.activeNode === modelData.id ? "#e0e0ff" : Theme.textDim
                            font.pixelSize: Theme.fontSizeSmall
                            font.family: Theme.fontMono
                        }
                    }
                }

                TapHandler {
                    onTapped: root.nodeSelected(modelData.id)
                }
            }
        }
    }
}
