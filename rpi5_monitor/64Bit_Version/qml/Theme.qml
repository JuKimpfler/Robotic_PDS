pragma Singleton
import QtQuick

// Zentrale Farb-/Maß-Konstanten.
//
// ── Woher die Werte kommen ──────────────────────────────────────────────────
// Alles hier steht in settings.json neben main_qml.py (Abschnitt "theme",
// siehe app_settings.py) und kommt über appBridge.settings.theme herein.
// Vorher waren die Farben und Maße hier fest verdrahtet — wer die Oberfläche
// an ein anderes Display anpassen wollte, musste diese Datei ändern und
// hatte die Änderung beim nächsten `git pull` im Weg.
//
// ── Hell/Dunkel und Schriftgröße (F7) ───────────────────────────────────────
// `dark` und `fontScale` kommen ebenfalls aus appBridge.settings und werden
// dort dauerhaft gespeichert (siehe bridge/settings_bridge.py). Weil ALLE
// Farben und Schriftgrößen hier durchlaufen, genügt das Umschalten dieser
// beiden Werte — jede daran hängende Bindung wertet sich von selbst neu aus,
// ohne dass irgendeine Ansicht neu geladen werden muss. Dasselbe gilt für
// einen kompletten Profilwechsel: SettingsBridge feuert dabei themeChanged,
// und `cfg`/`pal` unten hängen daran.
//
// Die Helligkeitsvariante ist bewusst kein bloßes Invertieren: auf einem
// 13"-Display in der Sonne braucht man kräftigere Kontraste und dunklere
// Akzentfarben, damit die Kurvenfarben auf Weiß noch lesbar sind.
QtObject {
    id: theme

    // Die Abfrage auf `undefined` ist kein Zierrat: Theme ist ein Singleton
    // und koennte theoretisch ausgewertet werden, bevor main_qml.py die
    // Kontext-Property appBridge gesetzt hat. Ohne den Schutz stuende dann
    // die komplette Oberflaeche ohne Farben da.
    readonly property bool available: (typeof appBridge !== "undefined")
                                      && appBridge.settings ? true : false
    readonly property bool dark: available ? appBridge.settings.dark : true
    readonly property real fontScale: available ? appBridge.settings.fontScale : 1.0

    // Der komplette "theme"-Abschnitt aus settings.json. `fallback` deckt
    // nur den Fall ab, dass es appBridge noch nicht gibt — im Normalbetrieb
    // ist der Abschnitt IMMER vollstaendig, weil die Python-Seite fehlende
    // Schluessel mit den Standardwerten auffuellt (app_settings.normalize).
    readonly property var cfg: available ? appBridge.settings.theme : fallback
    readonly property var pal: dark ? cfg.colors.dark : cfg.colors.light

    // ── Farben ───────────────────────────────────────────────────────────
    readonly property color bg:          pal.bg
    readonly property color bgMid:       pal.bgMid
    readonly property color bgAlt:       pal.bgAlt
    readonly property color bgInput:     pal.bgInput
    readonly property color text:        pal.text
    readonly property color textjulius:  pal.textjulius
    readonly property color textDim:     pal.textDim
    readonly property color highlight:   pal.highlight
    readonly property color accentBlue:  pal.accentBlue
    readonly property color accentGreen: pal.accentGreen
    readonly property color accentRed:   pal.accentRed
    readonly property color accentAmber: pal.accentAmber
    readonly property color border:      pal.border
    readonly property color ledOn:       pal.ledOn
    readonly property color ledOff:      pal.ledOff

    // Flächen für Warn-/Fehlerbanner (sonst überall als Literal verstreut)
    readonly property color warnBg:      pal.warnBg
    readonly property color errorBg:     pal.errorBg
    readonly property color okBg:        pal.okBg

    // ── Touch-Metriken ───────────────────────────────────────────────────
    readonly property int touchTargetMin: Math.round(cfg.touchTargetMin * fontScale)
    readonly property int spacingXs: cfg.spacing.xs
    readonly property int spacingS:  cfg.spacing.s
    readonly property int spacingM:  cfg.spacing.m
    readonly property int spacingL:  cfg.spacing.l

    readonly property int radiusS: cfg.radius.s
    readonly property int radiusM: cfg.radius.m
    readonly property int radiusL: cfg.radius.l

    readonly property int fontSizeSmall:  Math.round(cfg.fontSize.small * fontScale)
    readonly property int fontSizeTabell: Math.round(cfg.fontSize.table * fontScale)
    readonly property int fontSizeBase:   Math.round(cfg.fontSize.base * fontScale)
    readonly property int fontSizeLarge:  Math.round(cfg.fontSize.large * fontScale)
    readonly property int fontSizeXLarge: Math.round(cfg.fontSize.xlarge * fontScale)

    readonly property string fontMono: cfg.fontMono

    // Nur der Notnagel für "appBridge gibt es noch nicht" — die gültigen
    // Werte stehen in settings.json und in app_settings.DEFAULTS, NICHT
    // hier. Bewusst nur das dunkle Schema: ohne appBridge ist `dark` true.
    readonly property var fallback: ({
        "fontMono": "monospace",
        "touchTargetMin": 48,
        "spacing": { "xs": 4, "s": 8, "m": 16, "l": 24 },
        "radius": { "s": 4, "m": 8, "l": 14 },
        "fontSize": { "small": 13, "table": 16, "base": 15,
                      "large": 20, "xlarge": 24 },
        "colors": {
            "dark": {
                "bg": "#1e1e1e", "bgMid": "#2d2d30", "bgAlt": "#37393a",
                "bgInput": "#3c3f41", "text": "#d4d4d4",
                "textjulius": "#a5dc6e", "textDim": "#969696",
                "highlight": "#0078d7", "accentBlue": "#9cdcfe",
                "accentGreen": "#4ec9b0", "accentRed": "#f48771",
                "accentAmber": "#f0c060", "border": "#444444",
                "ledOn": "#2ecc71", "ledOff": "#e74c3c",
                "warnBg": "#3a2f00", "errorBg": "#3a1f1f", "okBg": "#1f3a2a"
            },
            "light": {
                "bg": "#f2f3f5", "bgMid": "#e2e5e9", "bgAlt": "#d6dae0",
                "bgInput": "#ffffff", "text": "#1c1f23",
                "textjulius": "#2f6b12", "textDim": "#5a6169",
                "highlight": "#0a5ca8", "accentBlue": "#12608f",
                "accentGreen": "#0d7a63", "accentRed": "#b3271a",
                "accentAmber": "#9a6b00", "border": "#b6bcc4",
                "ledOn": "#1e8a4c", "ledOff": "#c0392b",
                "warnBg": "#fff2cc", "errorBg": "#ffe0dd", "okBg": "#dff3e6"
            }
        }
    })
}
