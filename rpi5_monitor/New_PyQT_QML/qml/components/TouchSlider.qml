import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import App

// Ersatz für gui/tab_params.py::make_slider_widget. QSlider-Handle war
// 16px (kaum touch-tauglich) — hier min. 32px Durchmesser (Theme-Metrik).
Item {
    id: root
    property string label: ""
    property real from: 0
    property real to: 1
    property real value: 0
    property int decimals: 1
    signal moved(real value)

    height: 56

    Row {
        anchors.fill: parent
        spacing: Theme.spacingS

        Label {
            text: root.label
            width: 150
            color: Theme.text
            font.pixelSize: Theme.fontSizeBase
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
        }

        Slider {
            id: slider
            width: root.width - 150 - 80 - Theme.spacingS * 2
            anchors.verticalCenter: parent.verticalCenter
            from: root.from
            to: root.to
            value: root.value
            Material.accent: Theme.highlight
            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: 32; height: 32; radius: 16
                color: slider.pressed ? Theme.highlight : Qt.lighter(Theme.highlight, 1.2)
                border.color: Theme.highlight
            }
            background: Rectangle {
                x: slider.leftPadding
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.availableWidth; height: 6; radius: 3
                color: Theme.bgInput
                Rectangle {
                    width: slider.visualPosition * parent.width
                    height: parent.height; radius: 3
                    color: Theme.highlight
                }
            }
            onMoved: root.moved(value)
        }

        Label {
            text: slider.value.toFixed(root.decimals)
            width: 70
            horizontalAlignment: Text.AlignRight
            font.family: Theme.fontMono
            color: Theme.accentGreen
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
