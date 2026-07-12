pragma Singleton
import QtQuick

// Migrationsplan Abschnitt 6: zentrale Farb-/Maß-Konstanten, Ersatz für
// den grossen setStyleSheet(...)-String aus dem bisherigen main.py.
QtObject {
    // ── Farben (identisch zur bisherigen Dark-Palette in main.py) ────────
    readonly property color bg:          "#1e1e1e"
    readonly property color bgMid:       "#2d2d30"
    readonly property color bgAlt:       "#37393a"
    readonly property color bgInput:     "#3c3f41"
    readonly property color text:        "#d4d4d4"
    readonly property color textjulius:  "#a5dc6e"
    readonly property color textDim:     "#969696"
    readonly property color highlight:   "#0078d7"
    readonly property color accentBlue:  "#9cdcfe"
    readonly property color accentGreen: "#4ec9b0"
    readonly property color accentRed:   "#f48771"
    readonly property color accentAmber: "#f0c060"
    readonly property color border:      "#444444"
    readonly property color ledOn:       "#2ecc71"
    readonly property color ledOff:      "#e74c3c"

    // ── Touch-Metriken (Migrationsplan Abschnitt 5) ───────────────────────
    readonly property int touchTargetMin: 48
    readonly property int spacingXs: 4
    readonly property int spacingS:  8
    readonly property int spacingM:  16
    readonly property int spacingL:  24

    readonly property int radiusS: 4
    readonly property int radiusM: 8
    readonly property int radiusL: 14

    readonly property int fontSizeSmall: 13
    readonly property int fontSizeTabell: 16
    readonly property int fontSizeBase:  15
    readonly property int fontSizeLarge: 20
    readonly property int fontSizeXLarge: 24

    readonly property string fontMono: "monospace"
}
