pragma Singleton
import QtQuick

// Zentrale Farb-/Maß-Konstanten.
//
// ── Hell/Dunkel und Schriftgröße (F7) ───────────────────────────────────────
// `dark` und `fontScale` kommen aus appBridge.settings und werden dort
// dauerhaft gespeichert (siehe bridge/settings_bridge.py). Weil ALLE Farben
// und Schriftgrößen hier durchlaufen, genügt das Umschalten dieser beiden
// Werte — jede daran hängende Bindung wertet sich von selbst neu aus, ohne
// dass irgendeine Ansicht neu geladen werden muss.
//
// Die Helligkeitsvariante ist bewusst kein bloßes Invertieren: auf einem
// 13"-Display in der Sonne braucht man kräftigere Kontraste und dunklere
// Akzentfarben, damit die Kurvenfarben auf Weiß noch lesbar sind.
QtObject {
    id: theme

    readonly property bool dark: appBridge.settings.dark
    readonly property real fontScale: appBridge.settings.fontScale

    // ── Farben ───────────────────────────────────────────────────────────
    readonly property color bg:          dark ? "#1e1e1e" : "#f2f3f5"
    readonly property color bgMid:       dark ? "#2d2d30" : "#e2e5e9"
    readonly property color bgAlt:       dark ? "#37393a" : "#d6dae0"
    readonly property color bgInput:     dark ? "#3c3f41" : "#ffffff"
    readonly property color text:        dark ? "#d4d4d4" : "#1c1f23"
    readonly property color textjulius:  dark ? "#a5dc6e" : "#2f6b12"
    readonly property color textDim:     dark ? "#969696" : "#5a6169"
    readonly property color highlight:   dark ? "#0078d7" : "#0a5ca8"
    readonly property color accentBlue:  dark ? "#9cdcfe" : "#12608f"
    readonly property color accentGreen: dark ? "#4ec9b0" : "#0d7a63"
    readonly property color accentRed:   dark ? "#f48771" : "#b3271a"
    readonly property color accentAmber: dark ? "#f0c060" : "#9a6b00"
    readonly property color border:      dark ? "#444444" : "#b6bcc4"
    readonly property color ledOn:       dark ? "#2ecc71" : "#1e8a4c"
    readonly property color ledOff:      dark ? "#e74c3c" : "#c0392b"

    // Flächen für Warn-/Fehlerbanner (sonst überall als Literal verstreut)
    readonly property color warnBg:      dark ? "#3a2f00" : "#fff2cc"
    readonly property color errorBg:     dark ? "#3a1f1f" : "#ffe0dd"
    readonly property color okBg:        dark ? "#1f3a2a" : "#dff3e6"

    // ── Touch-Metriken ───────────────────────────────────────────────────
    readonly property int touchTargetMin: Math.round(48 * fontScale)
    readonly property int spacingXs: 4
    readonly property int spacingS:  8
    readonly property int spacingM:  16
    readonly property int spacingL:  24

    readonly property int radiusS: 4
    readonly property int radiusM: 8
    readonly property int radiusL: 14

    readonly property int fontSizeSmall:  Math.round(13 * fontScale)
    readonly property int fontSizeTabell: Math.round(16 * fontScale)
    readonly property int fontSizeBase:   Math.round(15 * fontScale)
    readonly property int fontSizeLarge:  Math.round(20 * fontScale)
    readonly property int fontSizeXLarge: Math.round(24 * fontScale)

    readonly property string fontMono: "monospace"
}
